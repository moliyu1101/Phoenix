import {Type} from "typebox";

// This extension contains no provider secret; only the task-scoped token is used.
export default async function phoenixTools(pi: any) {
  const base = process.env.CTF_MODEL_BASE_URL?.replace(/\/v1\/?$/, "");
  const token = process.env.CTF_TASK_TOKEN;
  if (!base || !token) return;
  async function call(name: string, payload: unknown) {
    const response = await fetch(`${base}/tools/${name}`, {method: "POST",
      headers: {Authorization: `Bearer ${token}`, "Content-Type": "application/json"},
      body: JSON.stringify(payload)});
    if (!response.ok) throw new Error(`Native tool request failed (${response.status})`);
    return response.json();
  }
  function schema(value: any, defs: any): any {
    if (value.$ref) return schema(defs[value.$ref.split("/").pop()], defs);
    if (value.anyOf) return Type.Union(value.anyOf.map((v: any) => schema(v, defs)));
    if (value.enum) return Type.Union(value.enum.map((v: any) => Type.Literal(v)));
    if (value.const !== undefined) return Type.Literal(value.const);
    const options = Object.fromEntries(Object.entries(value).filter(([k]) => ["description", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern"].includes(k)));
    if (value.type === "object") {
      const properties = Object.fromEntries(Object.entries(value.properties || {}).map(([key, v]) => {
        const prop = schema(v, defs);
        return [key, (value.required || []).includes(key) ? prop : Type.Optional(prop)];
      }));
      return Type.Object(properties, {additionalProperties: value.additionalProperties === undefined ? true : value.additionalProperties, ...options});
    }
    if (value.type === "array") return Type.Array(schema(value.items || {}, defs), options);
    if (value.type === "integer") return Type.Integer(options);
    if (value.type === "number") return Type.Number(options);
    if (value.type === "boolean") return Type.Boolean(options);
    if (value.type === "null") return Type.Null();
    if (value.type === "string") return Type.String(options);
    return Type.Any();
  }
  const catalog = await call("schema", {});
  for (const item of catalog.tools) {
    const tool = item.function;
    pi.registerTool({name: tool.name, label: tool.name, description: tool.description,
      parameters: schema(tool.parameters, tool.parameters.$defs || {}),
      async execute(toolCallId: string, params: unknown) {
        const result = await call(tool.name, {call_id: toolCallId, arguments: params});
        return {content: [{type: "text", text: JSON.stringify(result)}], details: result};
      }});
  }
}
