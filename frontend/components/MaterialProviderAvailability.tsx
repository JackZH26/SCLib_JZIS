"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { emptyProviderAvailability } from "@/lib/material-provider-availability";
import type { MaterialProviderAvailability, MaterialReferenceProvider, ProviderFieldAvailability } from "@/lib/material-provider-availability";

export interface MaterialProviderAvailabilitySnapshot {
  materialId: string;
  providers: Partial<Record<MaterialReferenceProvider, MaterialProviderAvailability>>;
  fields: Record<string, ProviderFieldAvailability[]>;
}
interface ContextValue extends MaterialProviderAvailabilitySnapshot {
  publish: (materialId: string, availability: MaterialProviderAvailability) => void;
}
const AvailabilityContext = createContext<ContextValue | null>(null);

function AvailabilityScope({ materialId, children }: { materialId: string; children: ReactNode }) {
  const [providers, setProviders] = useState<ContextValue["providers"]>({});
  const publish = useCallback((id: string, availability: MaterialProviderAvailability) => {
    if (id !== materialId) return;
    setProviders(current => ({ ...current, [availability.provider]: availability }));
  }, [materialId]);
  const value = useMemo<ContextValue>(() => {
    const fields: ContextValue["fields"] = {};
    for (const provider of Object.values(providers)) for (const field of Object.values(provider?.fields ?? {})) (fields[field.field] ??= []).push(field);
    return { materialId, providers, fields, publish };
  }, [materialId, providers, publish]);
  return <AvailabilityContext.Provider value={value}>{children}</AvailabilityContext.Provider>;
}

/** Changing material remounts the scope and drops reports from the previous page. */
export function MaterialProviderAvailabilityProvider({ materialId, children }: { materialId: string; children: ReactNode }) {
  return <AvailabilityScope key={materialId} materialId={materialId}>{children}</AvailabilityScope>;
}

export function useMaterialProviderAvailability(): MaterialProviderAvailabilitySnapshot | null {
  return useContext(AvailabilityContext);
}

/** A stable optional publisher keeps standalone lazy panels fully functional. */
export function useProviderAvailabilityPublisher(materialId: string, provider: MaterialReferenceProvider) {
  const publish = useContext(AvailabilityContext)?.publish;
  return useCallback((availability: MaterialProviderAvailability | null) => {
    publish?.(materialId, availability ?? emptyProviderAvailability(provider));
  }, [publish, materialId, provider]);
}
