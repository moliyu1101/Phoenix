/** Shared state for BLACKBOARD_DELTA domain reducers. */
import type { BlackboardView, DeckState, PhoenixEvent } from "../types";

export interface BlackboardReducerContext {
  ev: PhoenixEvent;
  s: DeckState;
  sid: string;
  p: Record<string, any>;
  bb: BlackboardView;
  actor: string;
  tlabel: (text: string, stableKey?: string) => void;
}
