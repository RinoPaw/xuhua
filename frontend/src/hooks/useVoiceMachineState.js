import { useCallback, useRef, useState } from "react";

import {
  createVoiceMachineState,
  deriveVoiceStatus,
  reduceVoiceDisplayStatus,
  reduceVoiceMachine,
} from "./voiceState.js";


export function useVoiceMachineState() {
  const [state, setState] = useState(() => createVoiceMachineState());
  const stateRef = useRef(state);
  stateRef.current = state;

  const commit = useCallback((next) => {
    stateRef.current = next;
    setState(next);
    return next;
  }, []);

  const dispatch = useCallback((action) => {
    return commit(reduceVoiceMachine(stateRef.current, action));
  }, [commit]);

  const setDisplayStatus = useCallback((status) => {
    return commit(reduceVoiceDisplayStatus(stateRef.current, status));
  }, [commit]);

  return {
    state,
    stateRef,
    status: deriveVoiceStatus(state),
    dispatch,
    setDisplayStatus,
  };
}

export default useVoiceMachineState;
