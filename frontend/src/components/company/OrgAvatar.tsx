const TINTS: Array<[string, string]> = [
  ["#dbeafe", "#1e40af"],
  ["#dcfce7", "#15803d"],
  ["#fef3c7", "#b45309"],
  ["#fce7f3", "#be185d"],
  ["#ede9fe", "#6d28d9"],
  ["#cffafe", "#0e7490"],
];

const SUFFIXES = new Set([
  "gmbh",
  "mbh",
  "ag",
  "se",
  "kg",
  "ug",
  "co",
  "ltd",
  "inc",
  "llc",
  "plc",
  "corp",
  "sa",
  "nv",
  "bv",
]);

export function orgInitials(name: string): string {
  const words = (name ?? "")
    .split(/[\s,&]+/)
    .map((word) => word.replace(/[^A-Za-zÀ-ÿ0-9]/g, ""))
    .filter(Boolean)
    .filter((word) => !SUFFIXES.has(word.toLowerCase()));
  if (words.length === 0) return "?";
  return words
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
}

function tintFor(name: string): [string, string] {
  let hash = 0;
  for (const char of name ?? "") hash = (hash * 31 + char.charCodeAt(0)) % 997;
  return TINTS[hash % TINTS.length];
}

export function OrgAvatar({
  name,
  size = 22,
  className = "",
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  const [background, color] = tintFor(name);
  return (
    <span
      aria-hidden
      className={`grid shrink-0 place-items-center rounded-[6px] font-bold ${className}`}
      style={{
        width: size,
        height: size,
        background,
        color,
        fontSize: Math.max(9, Math.round(size * 0.42)),
        letterSpacing: "0.02em",
      }}
    >
      {orgInitials(name)}
    </span>
  );
}
