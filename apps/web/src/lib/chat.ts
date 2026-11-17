import { initRun, runReducer, type RunAction, type RunState } from "./run";

export interface Turn {
  id: number;
  run: RunState;
}

export interface ChatState {
  turns: Turn[];
}

export type ChatAction =
  | { type: "turn_start"; id: number; message: string; failSource: "news" | undefined; at: number }
  | { type: "turn_action"; id: number; action: RunAction }
  | { type: "turn_restart"; id: number; at: number };

export const initialChat: ChatState = { turns: [] };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  if (action.type === "turn_start") {
    const turn = { id: action.id, run: initRun(action.message, action.failSource, action.at) };
    return { turns: [...state.turns, turn] };
  }
  if (action.type === "turn_restart") {
    return {
      turns: state.turns.map((t) =>
        t.id === action.id ? { ...t, run: initRun(t.run.message, t.run.failSource, action.at) } : t,
      ),
    };
  }
  return {
    turns: state.turns.map((t) =>
      t.id === action.id ? { ...t, run: runReducer(t.run, action.action) } : t,
    ),
  };
}

export const isRunning = (state: ChatState) => state.turns.some((t) => t.run.status === "running");
