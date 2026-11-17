import { test } from 'node:test';
import assert from 'node:assert/strict';
import { progressBins } from '../src/progressBins.ts';

test('progress ranges use each denominator and keep exact 0% and 100% separate', () => {
  const rows = [
    { assigned: 0, solved: 0 },
    { assigned: 10, solved: 0 },
    { assigned: 10000, solved: 999 },
    { assigned: 10, solved: 1 },
    { assigned: 30, solved: 3 },
    { assigned: 3, solved: 2 },
    { assigned: 10000, solved: 9999 },
    { assigned: 8, solved: 8 },
  ];
  const occupied = progressBins(rows, 10).filter(bin => bin.students.length);
  assert.deepEqual(occupied.map(({ lower, upper, students }) => [lower, upper, students.length]), [
    [0, 0, 1], [0, 10, 1], [10, 20, 2], [60, 70, 1], [90, 100, 1], [100, 100, 1],
  ]);
});

test('a finer step separates results that share a wider range', () => {
  const first = { id: 1, assigned: 100, solved: 12 };
  const second = { id: 2, assigned: 100, solved: 17 };
  const rows = [first, second];
  const occupied = step => progressBins(rows, step).filter(bin => bin.students.length);
  assert.deepEqual(occupied(5), [
    { lower: 10, upper: 15, students: [first] }, { lower: 15, upper: 20, students: [second] },
  ]);
  assert.deepEqual(occupied(10), [{ lower: 10, upper: 20, students: rows }]);
  assert.deepEqual(occupied(25), [{ lower: 0, upper: 25, students: rows }]);
});
