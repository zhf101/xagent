"use client"

import * as React from "react"
import { Check } from "lucide-react"

import { cn } from "@/lib/utils"

type CheckboxProps = Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "type" | "onChange"
> & {
  checked?: boolean
  onCheckedChange?: (checked: boolean) => void
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, checked = false, disabled, onCheckedChange, ...props }, ref) => {
    return (
      <label
        className={cn(
          "relative inline-flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded-sm border border-primary shadow-sm transition-colors",
          "focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 focus-within:ring-offset-background",
          checked ? "bg-primary text-primary-foreground" : "bg-background",
          disabled ? "cursor-not-allowed opacity-50" : "hover:bg-accent hover:text-accent-foreground",
          className
        )}
      >
        <input
          {...props}
          ref={ref}
          type="checkbox"
          checked={checked}
          disabled={disabled}
          className="sr-only"
          onChange={event => onCheckedChange?.(event.target.checked)}
        />
        <Check className={cn("h-3 w-3", checked ? "opacity-100" : "opacity-0")} />
      </label>
    )
  }
)

Checkbox.displayName = "Checkbox"

export { Checkbox }
