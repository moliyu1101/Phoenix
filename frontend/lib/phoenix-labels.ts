/** Presentation labels only. Wire values, identifiers and original content stay intact. */
const labels: Record<string,string> = {
 fixture:"脚本化验证",
 "At least three distinct held-out cases are required":"至少需要三个不同的留出样本。",
 "At least one previously solved case regressed":"存在基线已解出、候选未解出的回退样本。",
 "No solve-count improvement or >=10% token improvement at equal nonzero solves":"解题数未提升，或在相同非零解题数下未达到至少 10% 的词元改善。",
 "Cost increased by more than 25%":"费用增幅超过 25%。",
 "Uncertain billed calls prevent a trustworthy comparison":"存在计费结果待核对的调用，暂时无法可靠比较。",
 "Fixture/simulated models cannot authorize promotion":"脚本化验证不能用于策略发布。",
 planner:"规划器",analyst:"分析员",solver:"解题器",reviewer:"复核器",distiller:"蒸馏器",
 coordinator:"协调器",worker:"智能体",operator:"人工操作",system:"系统",model:"模型",
 settled:"已结算",reserved:"已预留",queued:"排队中",streaming:"生成中",connecting:"连接中",disconnected:"已断开",created:"待调度",running:"运行中",distilling:"蒸馏中",solved:"已确认",failed:"失败",
 paused:"已暂停",interrupted:"待恢复",exhausted:"已结束",awaiting_verification:"待验证",
 budget_exhausted:"预算耗尽",pending:"待领取",done:"已完成",blocked:"受阻",working:"工作中",
 draining:"完成当前任务后停用",standby:"待命",disabled:"已停用",finished:"已结束",
 accepted:"已接受",unverified:"未验证",rejected:"已拒绝",approved:"已批准",cancelled:"已取消",
 draft:"草稿",active:"已启用",retired:"已退役",candidate:"候选",baseline:"基线",
 live:"真实模型",demo:"脚本演示",heldout:"留出样本",paired:"成对评测",complete:"完整",
 completed:"已完成",partial:"部分记录",unknown:"未知",uncertain:"结果待核对",error:"错误",ok:"成功",
 absent:"未创建",unavailable:"不可用",exited:"已停止",open:"开放",closed:"关闭",hidden:"隐藏",
 correct:"正确",incorrect:"错误",duplicate:"重复提交",rate_limited:"请求过于频繁",submitted:"已提交",
 trusted:"已信任",untrusted:"未信任",quarantined:"待审核",retracted:"已撤回",imported:"已导入",
 procedure:"解题流程",lesson:"经验",episode:"运行记忆",semantic:"知识记忆",procedural:"流程记忆",
 observation:"观察",hypothesis:"假设",disproven:"已证伪",source:"来源",tool:"工具",sandbox:"沙箱",target:"题目目标",
 domain:"域名",subdomain:"子域名",ip:"IP 地址",port:"端口",site:"站点",endpoint:"端点",service:"服务",app:"应用",
 "challenge-scope":"题目目标", "http_request":"网络请求", "browser":"浏览器", "operator-replay":"人工重放",
 "scopesentry":"ScopeSentry 资产源", "api":"原生接口", "default":"默认配置", "pi-rpc":"Pi 远程执行",
 "operator-supplied exact SHA-256 verifier":"人工提供的精确校验值（SHA-256）",
 "distilled":"蒸馏经验", "failure":"失败经验", "success":"成功经验", "general":"通用", "auxiliary":"辅助调用",
 web:"网站安全",crypto:"密码学",pwn:"二进制利用",reverse:"逆向工程",forensics:"取证分析",misc:"杂项",
 file_inspect:"分析文件",decode:"解码数据",trajectory_search:"检索运行轨迹",fact_record:"记录事实",candidate_submit:"提交候选答案",task_finish:"完成任务",file_read:"读取文件",file_write:"写入文件",file_list:"列出文件",file_search:"检索文件",
 evidence_read:"读取证据",evidence_search:"检索证据",knowledge_search:"检索知识",memory_search:"检索记忆",
 sandbox_exec:"执行沙箱命令",tcp_exchange:"连接题目服务",browser_action:"操作浏览器",
 asset_add:"添加资产",asset_list:"查询资产",share_fact:"共享事实",report_fact:"记录事实",
 "assets.synced":"资产已同步","engine.event":"引擎运行事件","engine.started":"引擎已启动",
 "exchange.reconciled":"执行结果已协调","memory.distillation_interrupted":"经验蒸馏已中断",
 "memory.distillation_skipped":"已跳过经验蒸馏","memory.proposed":"经验草稿已生成","memory.rejected":"经验草稿未通过",
 "model.request":"发起模型请求","model.response":"模型响应已返回","operator.message":"人工补充消息",
 "planner.completed":"任务规划已完成","request.approval_decided":"拦截请求已处理","request.approval_required":"请求等待处理",
 "retrieval.lexical_fallback":"已切换到关键词检索","run.resume_acknowledged":"已确认恢复运行",
 "swarm.demo_result":"蜂群演示结果","swarm.initialized":"蜂群已初始化","swarm.scaled":"蜂群并行上限已调整",
 "swarm.unserviceable":"暂无可执行任务的智能体","swarm.worker_added":"智能体已加入编队","swarm.worker_enabled":"智能体启用状态已更新",
 "terminal.closed":"终端已关闭","terminal.opened":"终端已打开","traffic.recorded":"网络流量已记录",
 "worker.budget_stop":"智能体已达到预算上限","worker.context":"智能体上下文已更新",
 "run.created":"运行已创建","run.started":"运行已启动","run.state":"运行状态",
 "plan.added":"任务规划已更新","swarm.assigned":"智能体领取任务","worker.message":"智能体消息",
 "worker.finished":"任务交接","worker.error":"智能体执行失败","planner.error":"规划失败",
 "tool.started":"开始工具调用","tool.completed":"工具调用结束","evidence.created":"证据已记录",
 "fact.created":"共享发现","flag.verified":"答案验证","flag.operator_receipt":"答案人工回执",
 "sandbox.created":"沙箱已创建","sandbox.start":"沙箱已启动","sandbox.stop":"沙箱已停止",
 "sandbox.pause":"沙箱已暂停","sandbox.resume":"沙箱已恢复","run.continued":"继续解题",
};
export function uiLabel(value:unknown):string {const key=String(value??"");return labels[key]||labels[key.toLowerCase()]||key;}
export function roleLabels(roles:string[]=[]){return roles.map(uiLabel).join(" / ");}
const names:Record<string,string>={
 "Recon Analyst":"侦察分析员","Solver Alpha":"解题智能体甲","Solver Beta":"解题智能体乙",
 "Independent Reviewer":"独立复核员","Scout":"侦察智能体","Solver A":"解题智能体甲","Solver B":"解题智能体乙",
 "Reviewer":"复核智能体","Worker":"智能体","New 智能体":"新智能体",
};
export function workerDisplayName(name:string){return names[name]||name;}

const errorPatterns:[RegExp,string][]=[
 [/Pause the run before (executing an operator command|changing its sandbox lifecycle|opening|starting|taking over|reconciling)/i,"请先暂停本轮蜂群，再执行人工操作。"],
 [/Inputs are frozen after a run is created/i,"运行开始后附件已固定；修改附件请新建题目。"],
 [/Model profile for (\w+) is not configured/i,"尚未配置模型，请先在设置中完成模型连接。"],
 [/Only a terminal run can be manually distilled/i,"请在运行结束后再生成经验草稿。"],
 [/The run state changed/i,"运行状态已变化，请刷新后重试。"],
 [/No sandbox has been created/i,"尚未创建沙箱，请先启动题目沙箱。"],
 [/Docker is unavailable/i,"沙箱服务不可用，请检查服务器上的容器服务。"],
 [/Target.*(outside|scope)|not.*(allowed|authorized).*origin|outside.*scope/i,"此地址不在本题的目标范围内，请检查题目目标。"],
 [/Targets must be explicit|Specify an origin/i,"目标应填写完整的源站地址，不包含用户名、密码、路径或查询参数。"],
 [/TCP targets require a port|Invalid target port/i,"请为题目服务填写有效端口。"],
 [/Terminal disconnected/i,"终端连接已断开，请在保留的沙箱中打开新终端。"],
 [/Close an unused terminal/i,"终端会话数已达上限，请先关闭不用的终端。"],
 [/Invalid target URL/i,"目标地址无效，请填写完整的题目地址。"],
 [/credential is required/i,"请填写平台连接凭据。"],
 [/Unknown run|not found/i,"未找到对应记录，请刷新后重试。"],
 [/Timeout|timed out/i,"请求超时，请检查服务连接后重试。"],
 [/Failed to fetch|fetch failed|NetworkError|Load failed/i,"网络连接失败，请检查服务是否正常运行。"],
];
const fields:Record<string,string>={title:"题目名称",description:"题面",targets:"题目目标",kind:"类型",value:"内容",endpoint:"服务地址",url:"地址",model:"模型",timeout:"超时时间",concurrency:"并行上限",profiles:"模型配置",workers:"智能体",roles:"角色",flag_prefix:"答案前缀",command:"命令",body:"请求体",headers:"请求头"};
export function localizedError(value:unknown,status?:number):string {
 if(Array.isArray(value))return value.map((item:any)=>{
  const field=(item.loc||[]).filter((x:unknown)=>x!=="body").map((x:unknown)=>fields[String(x)]||(/^[0-9]+$/.test(String(x))?`第 ${Number(x)+1} 项`:"配置项")).join(" · ");
  const type=String(item.type||"");const reason=type.includes("missing")?"不能为空":type.includes("too_long")?"内容过长":type.includes("too_short")?"内容过短":type.includes("greater_than")?"数值过小":type.includes("less_than")?"数值过大":localizedError(item.msg||"输入格式不正确");
  return `${field||"输入"}：${reason}`;
 }).join("；");
 const text=typeof value==="string"?value:value&&typeof value==="object"?String((value as any).message||""):"";
 if(/not valid JSON|Unexpected token|JSON\.parse/i.test(text))return "数据格式错误，请检查结构化内容和引号。";
 if(/[\u3400-\u9fff]/.test(text))return text;
 for(const [pattern,translated] of errorPatterns)if(pattern.test(text))return translated;
 if(status===401)return "登录已失效，请重新输入工作台令牌。";
 if(status===403)return "请求被拒绝，请检查登录状态和访问地址。";
 if(status===409)return "当前状态暂不支持此操作，请刷新后重试。";
 if(status===422||status===400)return "输入内容不符合要求，请检查后重试。";
 return status?`服务请求失败（状态码 ${status}），请稍后重试。`:"操作失败，请检查输入或连接后重试。";
}
