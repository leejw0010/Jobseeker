import type { ApplicationDetail, EssayItem } from "../../types";

/** Versions are append-only; confirming a submission has its own revision. */
export function mergeEssayItem(current: EssayItem, incoming: EssayItem): EssayItem {
  const versions = new Map(current.versions.map((version) => [version.id, version]));
  for (const version of incoming.versions) {
    const previous = versions.get(version.id);
    versions.set(version.id, { ...version, is_submitted: version.is_submitted || !!previous?.is_submitted });
  }
  const submission = (current.submission_revision ?? 0) > (incoming.submission_revision ?? 0) ? current : incoming;
  return {
    ...incoming,
    versions: [...versions.values()].sort((left, right) => left.version_no - right.version_no),
    submitted_version_id: submission.submitted_version_id,
    submission_confirmation: submission.submission_confirmation,
    submission_revision: submission.submission_revision,
  };
}

/** A full response may predate an independent card save or a new item. Only explicit deletion removes local items. */
export function mergeApplicationDetail(current: ApplicationDetail | null, incoming: ApplicationDetail, deleted: ReadonlySet<string>): ApplicationDetail {
  const existing = new Map(current?.id === incoming.id ? current.essay_items.map((item) => [item.id, item]) : []);
  const items = incoming.essay_items.filter((item) => !deleted.has(item.id)).map((item) => {
    const previous = existing.get(item.id);
    existing.delete(item.id);
    return previous ? mergeEssayItem(previous, item) : item;
  });
  for (const item of existing.values()) if (!deleted.has(item.id)) items.push(item);
  return { ...incoming, essay_items: items };
}
