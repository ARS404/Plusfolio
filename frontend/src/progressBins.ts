export const progressSteps = [5, 10, 25] as const;
export type ProgressStep = typeof progressSteps[number];
export type StudentProgress = { assigned: number; solved: number };

export function progressBins<T extends StudentProgress>(rows: readonly T[], step: ProgressStep) {
  const bins: { lower: number; upper: number; students: T[] }[] = [{ lower: 0, upper: 0, students: [] }];
  for (let lower = 0; lower < 100; lower += step) {
    bins.push({ lower, upper: lower + step, students: [] });
  }
  bins.push({ lower: 100, upper: 100, students: [] });

  for (const row of rows) {
    const { assigned, solved } = row;
    if (!assigned) continue;
    let index;
    if (solved === 0) index = 0;
    else if (solved === assigned) index = bins.length - 1;
    else index = 1 + Math.floor(100 * solved / (step * assigned));
    bins[index].students.push(row);
  }
  return bins;
}
