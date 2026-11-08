import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Strategy, StrategyType } from "./types";

export function useStrategies(includeArchived = false) {
  const [strategies, setStrategies] = useState<Strategy[] | null>(null);
  const [types, setTypes] = useState<StrategyType[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([api.strategies(includeArchived), api.strategyTypes()]);
      setStrategies(s);
      setTypes(t);
    } catch (e) {
      setError(`Could not load strategies: ${(e as Error).message}`);
    }
  }, [includeArchived]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { strategies, types, error, reload };
}
