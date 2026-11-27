import { X } from 'lucide-react'

const SHORTCUTS: [string, string][] = [
  ['j / k or ↓ / ↑', 'Move focus'],
  ['1', 'Keep'],
  ['2', 'Correct / Edit gloss'],
  ['3', 'Check with AI'],
  ['4', 'Fill with AI'],
  ['s', 'Skip'],
  ['x', 'Toggle selection'],
  ['a', 'Apply suggestion'],
  ['u', 'Undo last decision / batch'],
  ['Enter', 'Save inline edit'],
  ['Esc', 'Cancel inline edit'],
  ['?', 'Toggle this sheet'],
]

export default function ShortcutsSheet({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-xl border border-gray-200 p-5 w-80"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-900">Keyboard shortcuts</h3>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-600">
            <X size={16} />
          </button>
        </div>
        <dl className="space-y-1.5">
          {SHORTCUTS.map(([key, desc]) => (
            <div key={key} className="flex items-center justify-between text-sm">
              <dt>
                <kbd className="px-1.5 py-0.5 rounded bg-gray-100 border border-gray-500 text-xs font-mono text-gray-700">
                  {key}
                </kbd>
              </dt>
              <dd className="text-gray-600">{desc}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
