import { useId, useMemo, useState, type CSSProperties } from 'react';
import { progressBins, progressSteps, type ProgressStep, type StudentProgress } from './progressBins';
import EntityId from './EntityId';
import './progress-histogram.css';

type HistogramStudent = StudentProgress & {
  id: number;
  name: string;
  public_id: string;
  can_view_profile?: boolean;
};

type Props = {
  rows: readonly HistogramStudent[];
  circleId?: string;
  median: number | null;
  step: ProgressStep;
  onStepChange: (step: ProgressStep) => void;
};

const countFormat = new Intl.NumberFormat('ru-RU');
const percentFormat = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 });

function rangeDescription({ lower, upper }: { lower: number; upper: number }) {
  if (lower === upper) return `${lower}%`;
  if (lower === 0) return `Больше 0%, меньше ${upper}%`;
  return `От ${lower}% до ${upper}% (не включая ${upper}%)`;
}

function HistogramStudents({ students, circleId }: { students: readonly HistogramStudent[]; circleId?: string }) {
  const [open, setOpen] = useState(false);
  const query = circleId ? `?${new URLSearchParams({ circle: circleId })}` : '';

  return <details className="histogram-students" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Школьники в диапазоне</summary>
    {open && <ul>
      {students.map(student => <li key={student.id}>
        <span>
          {student.can_view_profile === false ? student.name :
            <a className="student-profile-link" href={`#/students/${student.id}${query}`}>{student.name}</a>}
          <EntityId value={student.public_id}/>
        </span>
        <small>Решено {countFormat.format(student.solved)} из {countFormat.format(student.assigned)}</small>
      </li>)}
    </ul>}
  </details>;
}

export default function ProgressHistogram({ rows, median, step, onStepChange, circleId }: Props) {
  const titleId = useId();
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const bins = useMemo(() => progressBins(rows, step), [rows, step]);
  const total = bins.reduce((sum, bin) => sum + bin.students.length, 0);
  const maxCount = Math.max(1, ...bins.map(bin => bin.students.length));
  const tickStep = Math.ceil(maxCount / 4);
  const tickCount = Math.ceil(maxCount / tickStep);
  const axisMax = tickCount * tickStep;
  const selected = selectedIndex === null ? null : bins[selectedIndex];
  const share = (count: number) => percentFormat.format(total ? count / total : 0);

  return <section className="panel progress-histogram" aria-labelledby={titleId}>
    <div className="panel-heading">
      <div>
        <h3 id={titleId}>Как распределён прогресс</h3>
        <p>Доля решённых задач у каждого школьника. Ровно 0% и 100% показаны отдельно.</p>
      </div>
      <label className="histogram-step">
        Шаг диапазона
        <select value={step} onChange={event => {
          setSelectedIndex(null);
          onStepChange(Number(event.target.value) as ProgressStep);
        }}>
          {progressSteps.map(value => <option key={value} value={value}>{value} п. п.</option>)}
        </select>
      </label>
    </div>
    <div className="histogram-body">
      <div className="histogram-axis-label">Число школьников</div>
      <div className="histogram-scroll" role="region" aria-label="Гистограмма прогресса" tabIndex={0}>
        <div className="histogram-chart" style={{ '--bin-count': bins.length } as CSSProperties}>
          <div className="histogram-plot">
            {Array.from({ length: tickCount + 1 }, (_, index) => (
              <div key={index} className="histogram-guide" aria-hidden="true" style={{ bottom: `${100 * index / tickCount}%` }}>
                <span>{countFormat.format(index * tickStep)}</span>
              </div>
            ))}
            <div className="histogram-columns">
              {bins.map((bin, index) => {
                const { lower, upper, students } = bin;
                const count = students.length;
                const isSelected = index === selectedIndex;
                const label = lower === upper ? `${upper}%` : upper;
                const description = `${rangeDescription(bin)} · ${countFormat.format(count)} из ${countFormat.format(total)} (${share(count)})`;
                return <button key={index} type="button" className="histogram-column"
                  style={{ '--bar-height': `${100 * count / axisMax}%` } as CSSProperties}
                  title={description} aria-label={description} aria-pressed={isSelected}
                  onClick={() => setSelectedIndex(isSelected ? null : index)}>
                  <span className="histogram-bar" aria-hidden="true"/>
                  {isSelected && <span className="histogram-count" aria-hidden="true">{countFormat.format(count)}</span>}
                  <span className="histogram-range" aria-hidden="true">{label}</span>
                </button>;
              })}
            </div>
          </div>
        </div>
      </div>
      <p className="histogram-x-label">Верхняя граница диапазона, % · не входит в диапазон</p>
      <p className="histogram-detail" aria-live="polite">
        {selected ? <><b>{rangeDescription(selected)}</b> · {countFormat.format(selected.students.length)} из {countFormat.format(total)} школьников ({share(selected.students.length)})</>
          : 'Выберите столбец, чтобы увидеть долю школьников в диапазоне.'}
      </p>
      {selected && selected.students.length > 0 &&
        <HistogramStudents key={selectedIndex} students={selected.students} circleId={circleId}/>}
      <div className="histogram-summary">
        <span>Получателей <b>{countFormat.format(total)}</b></span>
        <span>Медиана <b>{median === null ? '—' : percentFormat.format(median / 100)}</b></span>
      </div>
    </div>
  </section>;
}
