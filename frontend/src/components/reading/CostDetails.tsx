import type { TextUsage } from '../../types'

export function formatCost(cost: number | null | undefined) {
  if (cost == null) return '—'
  return cost < 0.01 ? `$${cost.toFixed(4)}` : `$${cost.toFixed(3)}`
}

const STEP_LABEL: Record<string, string> = { write: 'Write', simplify: 'Simplify', check: 'Check' }

/** What creating a text cost, per model call, and the same tokens on other models. */
export default function CostDetails({ usage }: { usage: TextUsage }) {
  return (
    <details className="text-xs text-gray-600 border-t border-gray-100 pt-2">
      <summary className="cursor-pointer select-none">
        Cost to create: <span className="font-medium text-gray-700">{formatCost(usage.total_cost)}</span> ·{' '}
        {usage.input_tokens.toLocaleString()} tokens in, {usage.output_tokens.toLocaleString()} out
      </summary>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <table className="w-full">
          <thead>
            <tr className="text-gray-600">
              <th className="text-left font-normal">Step</th>
              <th className="text-right font-normal">In</th>
              <th className="text-right font-normal">Out</th>
              <th className="text-right font-normal">Cost</th>
            </tr>
          </thead>
          <tbody>
            {usage.calls.map((c, i) => (
              <tr key={i} title={c.model}>
                <td>{STEP_LABEL[c.step] ?? c.step}</td>
                <td className="text-right tabular-nums">{c.input_tokens.toLocaleString()}</td>
                <td className="text-right tabular-nums">{c.output_tokens.toLocaleString()}</td>
                <td className="text-right tabular-nums">{formatCost(c.cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <table className="w-full">
          <thead>
            <tr className="text-gray-600">
              <th className="text-left font-normal">Same tokens on</th>
              <th className="text-right font-normal">Est.</th>
            </tr>
          </thead>
          <tbody>
            {usage.estimates.map((e) => (
              <tr key={e.model}>
                <td>{e.label}</td>
                <td className="text-right tabular-nums">{formatCost(e.cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-gray-600">
        Estimates re-price these token counts at each model&apos;s rates. Other models think for different lengths,
        so treat them as a rough guide.
      </p>
    </details>
  )
}
