// Runs the Platane/snk solver on a saved GitHub contributionCalendar response, with the same
// calls as snk's own generator. Writes the untouched snk SVG and the real route.
//
// Usage: SNK_DIR=<checkout of Platane/snk> bun route.ts <calendar.json> <out dir> <output entry> [ms per step]
// <output entry> is the snk output option, for example "snake.svg?color_snake=#ffd23f&color_dots=...".
const SNK = process.env.SNK_DIR;
if (!SNK) throw new Error("SNK_DIR is not set");
const { getBestRoute } = await import(`${SNK}/packages/solver/getBestRoute`);
const { getPathToPose } = await import(`${SNK}/packages/solver/getPathToPose`);
const { createSvg } = await import(`${SNK}/packages/svg-creator`);
const { snake4 } = await import(`${SNK}/packages/types/__fixtures__/snake`);
const { snakeToCells } = await import(`${SNK}/packages/types/snake`);
const { cellsToGrid } = await import(`${SNK}/packages/generate-snake-animation/cellsToGrid`);
const { parseEntry } = await import(`${SNK}/packages/generate-snake-animation/outputsOptions`);

type Day = { contributionCount: number; contributionLevel: string; weekday: number; date: string };
type Cell = { x: number; y: number; date: string; count: number; level: number };

const [calendarPath, outDir, entry, stepMs] = process.argv.slice(2);
if (!calendarPath || !outDir || !entry) throw new Error("usage: bun route.ts <calendar.json> <out dir> <output entry>");

const LEVEL: Record<string, number> = { NONE: 0, FIRST_QUARTILE: 1, SECOND_QUARTILE: 2, THIRD_QUARTILE: 3, FOURTH_QUARTILE: 4 };
const response = await Bun.file(calendarPath).json();
if (response.errors?.length) throw new Error(`GraphQL: ${response.errors[0].message}`);
const weeks: { contributionDays: Day[] }[] = response.data.user.contributionsCollection.contributionCalendar.weeks;
const cells: Cell[] = weeks.flatMap(({ contributionDays }, x) =>
  contributionDays.map((d) => {
    if (!(d.contributionLevel in LEVEL)) throw new Error(`unknown contributionLevel ${d.contributionLevel}`);
    return { x, y: d.weekday, date: d.date, count: d.contributionCount, level: LEVEL[d.contributionLevel] };
  }),
);

const grid = cellsToGrid(cells);
const chain = getBestRoute(grid, snake4)!;
chain.push(...getPathToPose(chain.slice(-1)[0], snake4)!);

const options = parseEntry(entry);
if (!options || options.format !== "svg") throw new Error(`not an svg output entry: ${entry}`);
const { drawOptions, animationOptions } = options;
if (stepMs) {
  // snk moves one cell per 100 ms and has no option for it: a larger value slows the whole loop
  if (!(+stepMs >= 50 && +stepMs <= 1000)) throw new Error(`ms per step out of range: ${stepMs}`);
  animationOptions.stepDurationMs = +stepMs;
}
await Bun.write(`${outDir}/snk-raw.svg`, createSvg(grid, cells, chain, drawOptions, animationOptions));

// one eat = the first step whose head lands on a still-coloured cell (same rule as snk's svg-creator)
const left = new Map(cells.filter((c) => c.level > 0).map((c) => [`${c.x},${c.y}`, c]));
const snake: number[][][] = chain.map((s: unknown) => snakeToCells(s).map((p: { x: number; y: number }) => [p.x, p.y]));
const eats = [];
for (let step = 0; step < snake.length; step++) {
  const key = snake[step][0].join(",");
  const c = left.get(key);
  if (!c) continue;
  left.delete(key);
  eats.push({ step, ms: step * animationOptions.stepDurationMs, col: c.x, row: c.y, level: c.level, count: c.count, date: c.date });
}
if (left.size) throw new Error(`${left.size} coloured cells are never eaten`);

await Bun.write(
  `${outDir}/route.json`,
  JSON.stringify({
    stepMs: animationOptions.stepDurationMs,
    steps: chain.length,
    loopMs: chain.length * animationOptions.stepDurationMs,
    columns: grid.width,
    rows: grid.height,
    snake,
    eats,
    cells,
  }),
);
console.log(`route: ${chain.length} steps, ${chain.length * animationOptions.stepDurationMs} ms loop, ${eats.length} eats, ${cells.length} cells`);
