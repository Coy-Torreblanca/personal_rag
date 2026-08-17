"use client"

import * as DialogPrimitive from "@base-ui/react/dialog"

import { cn } from "@/lib/utils"

function Dialog(props: DialogPrimitive.DialogRoot.Props) {
  return <DialogPrimitive.Dialog.Root data-slot="dialog" {...props} />
}

function DialogTrigger(props: DialogPrimitive.DialogTrigger.Props) {
  return <DialogPrimitive.Dialog.Trigger data-slot="dialog-trigger" {...props} />
}

function DialogPortal(props: DialogPrimitive.DialogPortal.Props) {
  return <DialogPrimitive.Dialog.Portal data-slot="dialog-portal" {...props} />
}

function DialogClose(props: DialogPrimitive.DialogClose.Props) {
  return <DialogPrimitive.Dialog.Close data-slot="dialog-close" {...props} />
}

function DialogBackdrop({
  className,
  ...props
}: DialogPrimitive.DialogBackdrop.Props) {
  return (
    <DialogPrimitive.Dialog.Backdrop
      data-slot="dialog-backdrop"
      className={cn(
        "fixed inset-0 z-50 bg-black/80 data-[starting-style]:opacity-0 data-[starting-style]:animate-out data-[ending-style]:opacity-0",
        className
      )}
      {...props}
    />
  )
}

function DialogPopup({
  className,
  ...props
}: DialogPrimitive.DialogPopup.Props) {
  return (
    <DialogPrimitive.Dialog.Popup
      data-slot="dialog-popup"
      className={cn(
        "fixed left-1/2 top-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-lg border border-border bg-background p-6 shadow-lg duration-200 data-[starting-style]:opacity-0 data-[starting-style]:scale-95 data-[ending-style]:opacity-0 data-[ending-style]:scale-95",
        className
      )}
      {...props}
    />
  )
}

function DialogTitle({
  className,
  ...props
}: DialogPrimitive.DialogTitle.Props) {
  return (
    <DialogPrimitive.Dialog.Title
      data-slot="dialog-title"
      className={cn("text-lg font-semibold leading-none", className)}
      {...props}
    />
  )
}

function DialogDescription({
  className,
  ...props
}: DialogPrimitive.DialogDescription.Props) {
  return (
    <DialogPrimitive.Dialog.Description
      data-slot="dialog-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

export {
  Dialog,
  DialogClose,
  DialogTrigger,
  DialogPortal,
  DialogBackdrop,
  DialogPopup,
  DialogTitle,
  DialogDescription,
}
