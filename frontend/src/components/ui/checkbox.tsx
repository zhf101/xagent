"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

interface CheckboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> {
  checked?: boolean
  onCheckedChange?: (checked: boolean) => void
}

function Checkbox({
  className,
  checked = false,
  onCheckedChange,
  ...props
}: CheckboxProps) {
  return (
    <input
      type="checkbox"
      className={cn(
        "h-4 w-4 rounded border border-input bg-background align-middle accent-primary",
        className
      )}
      checked={checked}
      onChange={event => onCheckedChange?.(event.target.checked)}
      {...props}
    />
  )
}

export { Checkbox }
