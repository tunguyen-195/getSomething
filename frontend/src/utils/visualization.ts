export type LegacyVisualizationData = {
  nodes?: Array<Record<string, any>>;
  edges?: Array<Record<string, any>>;
  timeline?: Array<Record<string, any>>;
  main_events?: string[];
  entity_types?: string[];
  extracted_entities?: Array<Record<string, any>>;
  [key: string]: any;
};

export const getLegacyVisualizationData = <T extends LegacyVisualizationData>(
  data?: (T & { legacy_view?: T }) | null,
): T => {
  if (!data) {
    return {} as T;
  }
  if (data.legacy_view && typeof data.legacy_view === 'object') {
    return data.legacy_view;
  }
  return data;
};
