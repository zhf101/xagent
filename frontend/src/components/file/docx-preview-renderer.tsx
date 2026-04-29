"use client"

import { useEffect, useRef, useState } from "react"
import { useI18n } from "@/contexts/i18n-context"

interface DocxPreviewRendererProps {
  base64Content: string
}

export function DocxPreviewRenderer({ base64Content }: DocxPreviewRendererProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { t } = useI18n()

  useEffect(() => {
    let cancelled = false
    const container = containerRef.current

    const render = async () => {
      if (!container || !base64Content) {
        if (!cancelled) {
          setError(null)
        }
        return
      }

      try {
        const binary = atob(base64Content)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i)
        }

        container.innerHTML = ""
        const docxPreview = await import("docx-preview")
        if (cancelled) {
          return
        }

        await docxPreview.renderAsync(bytes.buffer, container, undefined, {
          className: "docx-preview",
          inWrapper: true,
          useBase64URL: true,
        })

        if (!cancelled) {
          setError(null)
        }
      } catch {
        if (!cancelled) {
          setError(t("files.previewDialog.errors.docxRenderFailed"))
        }
      }
    }

    void render()

    return () => {
      cancelled = true
      // 这里主动清空预览容器，避免上一次文档的 DOM 片段在组件卸载后残留，
      // 也避免异步渲染较慢时，旧内容在下一次挂载前短暂闪回。
      container?.replaceChildren()
    }
  }, [base64Content, t])

  if (error) {
    return <div className="p-4 text-sm text-muted-foreground">{error}</div>
  }

  return <div ref={containerRef} className="h-full overflow-auto bg-muted/30" />
}
