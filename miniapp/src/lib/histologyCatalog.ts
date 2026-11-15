import type { HistologyCatalogGroup } from "./types";

export interface HistologyCatalogLocation {
  catalogPath: "/histology/diagnostics" | "/histology/exam/specimens";
  catalogSearch: string;
}

export function filterHistologyGroups(groups: HistologyCatalogGroup[], search: URLSearchParams) {
  const group = search.get("group");
  const words = (search.get("q") ?? "").trim().toLocaleLowerCase("ru").replaceAll("ё", "е")
    .replace(/№\s*(?=\d)/g, "").split(/\s+/).filter(Boolean);
  const scope = groups.some((item) => item.id === group) ? groups.filter((item) => item.id === group) : groups;
  if (!words.length) return scope;

  return scope.map((item) => ({
    ...item,
    specimens: item.specimens.filter((specimen) => {
      const text = `${specimen.title} ${specimen.stain ?? ""}`.toLocaleLowerCase("ru").replaceAll("ё", "е");
      return words.every((word) => /^\d+$/.test(word)
        ? Number(word) === specimen.number
        : text.includes(word));
    }),
  })).filter((item) => item.specimens.length > 0);
}
