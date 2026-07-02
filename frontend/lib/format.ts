export function formatDate(value: string | null | undefined) {
  if (!value) {
    return "Pending";
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en").format(value);
}

export function formatLatency(ms: number) {
  if (ms < 1000) {
    return `${ms} ms`;
  }
  return `${(ms / 1000).toFixed(2)}s`;
}

export function formatBytes(value: number | null | undefined) {
  if (!value) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unit]}`;
}

export function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "0%";
  }
  return `${Math.round(value * 100)}%`;
}

export function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "0.00";
  }
  return value.toFixed(2);
}

export function lineRange(
  start: number | null,
  end: number | null,
  page?: number | null,
) {
  if (page) {
    if (start && end) {
      return `Page ${page}, lines ${start}-${end}`;
    }
    return `Page ${page}`;
  }
  if (start && end) {
    return `Lines ${start}-${end}`;
  }
  if (start) {
    return `Line ${start}`;
  }
  return "Source range unavailable";
}
