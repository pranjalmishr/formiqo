// shadcn/ui-style source-owned Button: Radix Slot + CVA variants.
import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
const variants = cva('inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50', {variants:{variant:{default:'bg-accent text-white hover:bg-indigo-700',outline:'border border-slate-200 bg-white text-ink hover:bg-slate-50',ghost:'text-slate-600 hover:bg-slate-100',destructive:'bg-red-600 text-white hover:bg-red-700'}},defaultVariants:{variant:'default'}});
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof variants> {asChild?: boolean}
export const Button = React.forwardRef<HTMLButtonElement,ButtonProps>(({className,variant,asChild=false,...props},ref)=>{const Comp=asChild?Slot:'button';return <Comp className={twMerge(clsx(variants({variant}),className))} ref={ref} {...props}/>});
Button.displayName='Button';
