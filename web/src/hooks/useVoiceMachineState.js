import { useCallback, useRef, useState } from "react";

import {
  createVoiceMachineState,
  deriveVoiceStatus,
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

  const dispatchMany = useCallback((actions) => {
    const next = (Array.isArray(actions) ? actions : []).reduce(
      (current, action) => reduceVoiceMachine(current, action),
      stateRef.current,
    );
    return commit(next);
  }, [commit]);

  const dispatch = useCallback((action) => dispatchMany([action]), [dispatchMany]);

  return {
    state,
    stateRef,
    status: deriveVoiceStatus(state),
    dispatch,
    dispatchMany,
  };
}

export default useVoiceMachineState;
