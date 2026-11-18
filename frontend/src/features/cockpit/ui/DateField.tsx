// The cockpit's date input (ELI-53) — see `datePicker.ts` for why.

import { forwardRef, type InputHTMLAttributes } from 'react'

import { openPicker, presetFor, type DateFieldType } from './datePicker'

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value' | 'onChange'> & {
  type?: DateFieldType
  value: string
  onChange: (value: string) => void
}

export const DateField = forwardRef<HTMLInputElement, Props>(function DateField(
  { type = 'date', value, onChange, onClick, ...rest },
  ref,
) {
  return (
    <input
      {...rest}
      ref={ref}
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onClick={(e) => {
        onClick?.(e)
        if (rest.disabled || rest.readOnly) return
        const preset = presetFor(type, value)
        if (preset !== null) onChange(preset)
        openPicker(e.currentTarget)
      }}
    />
  )
})
