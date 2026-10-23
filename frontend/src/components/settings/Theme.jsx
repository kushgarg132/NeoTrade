import React from 'react';
import Card from '../ui/Card';
import { useTheme } from '../../context/useTheme';

const OPTIONS = [['light', 'Light'], ['dark', 'Dark']];

const Theme = () => {
  const { theme, setTheme } = useTheme();
  return (
    <Card title="Appearance">
      <p className="mb-3 text-[14px] text-[var(--text-muted)]">Changes every screen on this device. Dark is easier on the eyes at night.</p>
      <div role="radiogroup" aria-label="Theme" className="flex gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
        {OPTIONS.map(([id, label]) => (
          <button key={id} type="button" role="radio" aria-checked={theme === id} onClick={() => setTheme(id)}
                  className={`flex-1 min-h-11 rounded-[8px] text-[15px] font-medium ${theme === id ? 'bg-[var(--surface)] text-[var(--text)] shadow-sm' : 'text-[var(--text-muted)]'}`}>
            {label}
          </button>
        ))}
      </div>
    </Card>
  );
};

export default Theme;
