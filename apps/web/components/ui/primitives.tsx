"use client";

import { cva, type VariantProps } from "class-variance-authority";
import { Loader2, X } from "lucide-react";
import { Collapsible as C, Dialog as D, DropdownMenu as DM, Slot, Switch as Sw, Tabs as T, Tooltip as Tt } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

// --- Button -------------------------------------------------------------------------------------

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition-[background,color,border,box-shadow] disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0 select-none",
  {
    variants: {
      variant: {
        primary: "bg-text text-bg hover:bg-text/90 shadow-1",
        signal: "bg-signal text-[#04212a] hover:brightness-110 shadow-1",
        secondary: "bg-surface text-text border border-line-strong hover:bg-surface-2",
        ghost: "text-text-2 hover:bg-surface-2 hover:text-text",
        danger: "bg-danger text-white hover:brightness-110",
        link: "text-signal underline-offset-4 hover:underline px-0 h-auto",
      },
      size: {
        sm: "h-8 rounded-md px-3 text-[13px]",
        md: "h-10 rounded-lg px-4 text-sm",
        lg: "h-12 rounded-xl px-6 text-[15px]",
        icon: "h-9 w-9 rounded-lg",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild, loading, children, disabled, ...props }, ref) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} disabled={disabled || loading}
      aria-busy={loading || undefined} {...props}>
      {asChild ? children : (<>{loading && <Loader2 className="animate-spin" aria-hidden />}{children}</>)}
    </Comp>
  );
});

// --- Inputs -------------------------------------------------------------------------------------

const fieldBase = "w-full rounded-lg border border-line-strong bg-surface px-3 text-sm text-text placeholder:text-muted/80 transition-colors focus-visible:outline-none focus-visible:border-signal focus-visible:ring-2 focus-visible:ring-signal/25 disabled:opacity-60 aria-[invalid=true]:border-danger";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props }, ref) {
  return <input ref={ref} className={cn(fieldBase, "h-10", className)} {...props} />;
});

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return <textarea ref={ref} className={cn(fieldBase, "py-2.5 leading-relaxed", className)} {...props} />;
  });

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...props }, ref) {
  return (
    <select ref={ref} className={cn(fieldBase, "h-10 appearance-none bg-[length:16px] bg-[right_10px_center] bg-no-repeat pr-9", className)}
      style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23889' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" }}
      {...props}>
      {children}
    </select>
  );
});

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("text-[13px] font-medium text-text-2", className)} {...props} />;
}

export function Field({ label, htmlFor, error, hint, children, className }: {
  label: string; htmlFor: string; error?: string; hint?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error ? <p id={`${htmlFor}-error`} role="alert" className="text-[13px] text-danger">{error}</p>
        : hint ? <p className="text-[12.5px] text-muted">{hint}</p> : null}
    </div>
  );
}

// --- Badge ---------------------------------------------------------------------------------------

const badgeVariants = cva("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium leading-5 whitespace-nowrap", {
  variants: {
    tone: {
      neutral: "bg-surface-2 text-text-2 border border-line",
      signal: "bg-signal-soft text-signal",
      lamp: "bg-lamp-soft text-lamp-ink",
      ok: "bg-ok-soft text-ok",
      warn: "bg-warn-soft text-warn",
      danger: "bg-danger-soft text-danger",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ tone, className, ...props }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

// --- Panels ---------------------------------------------------------------------------------------

export function Panel({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-[var(--radius-lg)] border border-line bg-surface", className)} {...props} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-md", className)} aria-hidden />;
}

export function IndeterminateBar({ className, label }: { className?: string; label?: string }) {
  return (
    <div className={cn("relative h-1 overflow-hidden rounded-full bg-signal-soft", className)} role="progressbar"
      aria-label={label ?? "In progress"} aria-busy="true">
      <div className="absolute inset-y-0 w-2/5 rounded-full bg-signal" style={{ animation: "indeterminate 1.5s cubic-bezier(.4,0,.2,1) infinite" }} />
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: React.ReactNode; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-[var(--radius-lg)] border border-dashed border-line-strong px-6 py-10">
      {icon && <div className="text-muted [&_svg]:size-6">{icon}</div>}
      <h3 className="headline text-xl">{title}</h3>
      {children && <div className="max-w-[60ch] text-text-2">{children}</div>}
      {action}
    </div>
  );
}

export function Notice({ tone = "neutral", title, children, action, className }: {
  tone?: "neutral" | "warn" | "danger" | "signal" | "lamp" | "ok"; title?: string; children?: React.ReactNode; action?: React.ReactNode; className?: string;
}) {
  const tones = {
    neutral: "border-line bg-surface-2", warn: "border-warn/30 bg-warn-soft", danger: "border-danger/30 bg-danger-soft",
    signal: "border-signal/30 bg-signal-soft", lamp: "border-lamp/30 bg-lamp-soft", ok: "border-ok/30 bg-ok-soft",
  } as const;
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex flex-col gap-2 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between", tones[tone], className)}>
      <div className="space-y-0.5 text-sm">
        {title && <p className="font-semibold text-text">{title}</p>}
        {children && <div className="text-text-2">{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

// --- Dialog / Sheet ------------------------------------------------------------------------------

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({ title, description, children, className, side }: {
  title: string; description?: React.ReactNode; children: React.ReactNode; className?: string; side?: "right";
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] data-[state=open]:animate-in" />
      <D.Content
        className={cn(
          "fixed z-50 border border-line bg-surface shadow-2 focus:outline-none",
          side === "right"
            ? "inset-y-0 right-0 flex h-full w-full max-w-[560px] flex-col border-y-0 border-r-0"
            : "left-1/2 top-1/2 max-h-[88vh] w-[min(560px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl p-6",
          className,
        )}>
        <div className={cn("flex items-start justify-between gap-4", side === "right" && "border-b border-line px-6 py-4")}>
          <div>
            <D.Title className="headline text-[22px]">{title}</D.Title>
            {description ? <D.Description className="mt-1 text-sm text-muted">{description}</D.Description>
              : <D.Description className="sr-only">{title}</D.Description>}
          </div>
          <D.Close className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text" aria-label="Close">
            <X className="size-4" />
          </D.Close>
        </div>
        <div className={cn(side === "right" ? "flex-1 overflow-y-auto px-6 py-5" : "mt-5")}>{children}</div>
      </D.Content>
    </D.Portal>
  );
}

// --- Menus, tabs, tooltip, switch, collapsible ------------------------------------------------------

export const Menu = DM.Root;
export const MenuTrigger = DM.Trigger;
export function MenuContent({ children, align = "end" }: { children: React.ReactNode; align?: "start" | "end" }) {
  return (
    <DM.Portal>
      <DM.Content align={align} sideOffset={6}
        className="z-50 min-w-[200px] rounded-xl border border-line bg-surface p-1.5 shadow-2">
        {children}
      </DM.Content>
    </DM.Portal>
  );
}
export function MenuItem({ className, ...props }: React.ComponentProps<typeof DM.Item>) {
  return <DM.Item className={cn("flex cursor-pointer select-none items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-text-2 outline-none data-[highlighted]:bg-surface-2 data-[highlighted]:text-text [&_svg]:size-4", className)} {...props} />;
}
export const MenuSeparator = () => <DM.Separator className="my-1 h-px bg-line" />;
export const MenuLabel = ({ children }: { children: React.ReactNode }) => (
  <DM.Label className="px-2.5 py-1.5 text-[12px] text-muted">{children}</DM.Label>
);

export const Tabs = T.Root;
export function TabsList({ className, ...props }: React.ComponentProps<typeof T.List>) {
  return <T.List className={cn("inline-flex items-center gap-1 rounded-xl border border-line bg-surface-2 p-1", className)} {...props} />;
}
export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof T.Trigger>) {
  return <T.Trigger className={cn("rounded-lg px-3 py-1.5 text-[13px] font-medium text-muted transition-colors hover:text-text data-[state=active]:bg-surface data-[state=active]:text-text data-[state=active]:shadow-1", className)} {...props} />;
}
export const TabsContent = T.Content;

export function Tooltip({ content, children, side = "top" }: { content: React.ReactNode; children: React.ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <Tt.Provider delayDuration={250}>
      <Tt.Root>
        <Tt.Trigger asChild>{children}</Tt.Trigger>
        <Tt.Portal>
          <Tt.Content side={side} sideOffset={6} className="z-50 max-w-[300px] rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12.5px] leading-snug text-text-2 shadow-2">
            {content}
          </Tt.Content>
        </Tt.Portal>
      </Tt.Root>
    </Tt.Provider>
  );
}

export function Switch({ className, ...props }: React.ComponentProps<typeof Sw.Root>) {
  return (
    <Sw.Root className={cn("relative h-6 w-10 shrink-0 rounded-full border border-line-strong bg-surface-2 transition-colors data-[state=checked]:border-signal data-[state=checked]:bg-signal", className)} {...props}>
      <Sw.Thumb className="block size-[18px] translate-x-[2px] rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
    </Sw.Root>
  );
}

export const Collapsible = C.Root;
export const CollapsibleTrigger = C.Trigger;
export const CollapsibleContent = C.Content;

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border border-line-strong bg-surface-2 px-1.5 py-0.5 font-sans text-[11px] text-muted">{children}</kbd>;
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-[13px] text-muted">{label}</p>
      <p className="text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
      {hint && <p className="text-[12.5px] text-muted">{hint}</p>}
    </div>
  );
}
