export function localDay(now = new Date()) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
export function weekForDate(start: string, today = localDay()) {
  return (
    Math.floor(
      (Date.parse(`${today}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) /
        604800000,
    ) + 1
  );
}
export function validDate(value: string) {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value
  );
}
