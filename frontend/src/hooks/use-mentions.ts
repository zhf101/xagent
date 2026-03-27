/**
 * @ 提及（Mention）能力 hook。
 *
 * 负责：
 * - 检测输入框中的 @ 触发
 * - 根据类别关键词（系统/数据库/模板）路由到对应 API
 * - 管理 picker 状态、搜索过滤、键盘导航
 * - 选中后插入 @类别[值] 格式文本
 */

import { useState, useCallback, useRef } from "react"
import { apiRequest } from "@/lib/api-wrapper"
import { getApiUrl } from "@/lib/utils"

/** 后端返回的统一 mention 条目 */
export interface MentionItem {
  id: string
  label: string
  value: string
  description?: string
}

/** 支持的 @ 类别定义 */
export interface MentionCategory {
  /** 后端 category 参数值 */
  key: string
  /** 触发关键词（中文），如 "系统"、"数据库"、"模板" */
  trigger: string
  /** 显示名称 */
  displayName: string
  /** 图标名（lucide icon name） */
  icon: string
}

/** 预定义的 @ 类别 */
export const MENTION_CATEGORIES: MentionCategory[] = [
  { key: "environment", trigger: "环境", displayName: "环境", icon: "cloud" },
  { key: "system", trigger: "系统", displayName: "系统", icon: "server" },
  { key: "database", trigger: "数据库", displayName: "数据库", icon: "database" },
  { key: "template", trigger: "模板", displayName: "模板", icon: "file-text" },
]

/** 类别选择阶段的候选项（输入 @ 后、还没输入类别关键词时显示） */
const CATEGORY_ITEMS: MentionItem[] = MENTION_CATEGORIES.map((c) => ({
  id: c.key,
  label: c.displayName,
  value: c.key,
  description: `@${c.trigger} 快速引用`,
}))

export interface UseMentionsReturn {
  /** picker 是否可见 */
  showMentionPicker: boolean
  /** 当前候选列表 */
  mentionItems: MentionItem[]
  /** 当前选中索引 */
  selectedMentionIndex: number
  /** 是否正在加载 */
  isLoadingMentions: boolean
  /** 当前阶段："category" 选类别 | "items" 选具体条目 */
  mentionPhase: "category" | "items"
  /** 当前选中的类别（items 阶段） */
  activeCategory: MentionCategory | null
  /** 检测触发（在 onChange 中调用） */
  checkMentionTrigger: (text: string, cursor: number) => void
  /** 选中一个条目 */
  selectMentionItem: (item: MentionItem, getMessage: () => string, setMessage: (v: string) => void) => void
  /** 键盘导航：上 */
  mentionNavUp: () => void
  /** 键盘导航：下 */
  mentionNavDown: () => void
  /** 关闭 picker */
  closeMentionPicker: () => void
  /** 当前触发位置 */
  mentionTriggerIndex: number
}

export function useMentions(): UseMentionsReturn {
  const [showMentionPicker, setShowMentionPicker] = useState(false)
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([])
  const [selectedMentionIndex, setSelectedMentionIndex] = useState(0)
  const [isLoadingMentions, setIsLoadingMentions] = useState(false)
  const [mentionPhase, setMentionPhase] = useState<"category" | "items">("category")
  const [activeCategory, setActiveCategory] = useState<MentionCategory | null>(null)
  const [mentionTriggerIndex, setMentionTriggerIndex] = useState(-1)

  // 缓存已加载的数据，避免重复请求
  const cacheRef = useRef<Record<string, MentionItem[]>>({})

  const fetchMentionItems = useCallback(async (category: string, query: string) => {
    // 有缓存且无搜索词时直接用缓存
    const cacheKey = category
    if (!query && cacheRef.current[cacheKey]) {
      return cacheRef.current[cacheKey]
    }

    setIsLoadingMentions(true)
    try {
      const params = new URLSearchParams({ category })
      if (query) params.set("q", query)
      const response = await apiRequest(`${getApiUrl()}/api/mentions?${params}`)
      if (response.ok) {
        const data = await response.json()
        if (Array.isArray(data)) {
          if (!query) cacheRef.current[cacheKey] = data
          return data as MentionItem[]
        }
      }
    } catch (e) {
      console.error("[useMentions] fetch failed:", e)
    } finally {
      setIsLoadingMentions(false)
    }
    return []
  }, [])

  const checkMentionTrigger = useCallback(
    (text: string, cursor: number) => {
      const textBeforeCursor = text.slice(0, cursor)
      const lastAtIndex = textBeforeCursor.lastIndexOf("@")

      if (lastAtIndex === -1) {
        setShowMentionPicker(false)
        setMentionTriggerIndex(-1)
        return
      }

      const query = textBeforeCursor.slice(lastAtIndex + 1)
      // @ 后面不能有换行
      if (query.includes("\n")) {
        setShowMentionPicker(false)
        setMentionTriggerIndex(-1)
        return
      }

      setMentionTriggerIndex(lastAtIndex)
      setShowMentionPicker(true)

      // 判断是否已经匹配到某个类别关键词
      const matchedCategory = MENTION_CATEGORIES.find((c) => query.startsWith(c.trigger))

      if (matchedCategory) {
        // 已匹配类别，进入 items 阶段
        const subQuery = query.slice(matchedCategory.trigger.length).trim()
        setMentionPhase("items")
        setActiveCategory(matchedCategory)

        // 异步加载数据
        fetchMentionItems(matchedCategory.key, subQuery).then((items) => {
          setMentionItems(items)
          setSelectedMentionIndex(0)
        })
      } else {
        // 还在选类别阶段
        setMentionPhase("category")
        setActiveCategory(null)
        const lowerQuery = query.toLowerCase()
        const filtered = CATEGORY_ITEMS.filter(
          (item) =>
            item.label.toLowerCase().includes(lowerQuery) ||
            item.description?.toLowerCase().includes(lowerQuery)
        )
        setMentionItems(filtered)
        setSelectedMentionIndex(0)
      }
    },
    [fetchMentionItems]
  )

  const selectMentionItem = useCallback(
    (item: MentionItem, getMessage: () => string, setMessage: (v: string) => void) => {
      if (mentionPhase === "category") {
        // 选了类别 → 替换 @xxx 为 @类别关键词，继续进入 items 阶段
        const cat = MENTION_CATEGORIES.find((c) => c.key === item.value)
        if (!cat) return

        const currentText = getMessage()
        if (mentionTriggerIndex === -1) return

        // 找到 @ 后面的文本结束位置
        let endIndex = currentText.indexOf(" ", mentionTriggerIndex)
        if (endIndex === -1) endIndex = currentText.indexOf("\n", mentionTriggerIndex)
        if (endIndex === -1) endIndex = currentText.length

        const prefix = currentText.slice(0, mentionTriggerIndex)
        const suffix = currentText.slice(endIndex)
        const newText = prefix + `@${cat.trigger}` + suffix
        setMessage(newText)

        // 进入 items 阶段
        setMentionPhase("items")
        setActiveCategory(cat)
        fetchMentionItems(cat.key, "").then((items) => {
          setMentionItems(items)
          setSelectedMentionIndex(0)
        })
      } else {
        // 选了具体条目 → 插入 @类别[值] 格式
        const currentText = getMessage()
        if (mentionTriggerIndex === -1) return

        let endIndex = currentText.indexOf(" ", mentionTriggerIndex)
        if (endIndex === -1) endIndex = currentText.indexOf("\n", mentionTriggerIndex)
        if (endIndex === -1) endIndex = currentText.length

        const prefix = currentText.slice(0, mentionTriggerIndex)
        const suffix = currentText.slice(endIndex)
        const catName = activeCategory?.trigger || "引用"
        const insertText = `@${catName}[${item.value}] `
        const newText = prefix + insertText + suffix
        setMessage(newText)

        // 关闭 picker
        setShowMentionPicker(false)
        setMentionTriggerIndex(-1)
        setMentionPhase("category")
        setActiveCategory(null)
      }
    },
    [mentionPhase, mentionTriggerIndex, activeCategory, fetchMentionItems]
  )

  const mentionNavUp = useCallback(() => {
    setSelectedMentionIndex((prev) => Math.max(0, prev - 1))
  }, [])

  const mentionNavDown = useCallback(() => {
    setSelectedMentionIndex((prev) => Math.min(mentionItems.length - 1, prev + 1))
  }, [mentionItems.length])

  const closeMentionPicker = useCallback(() => {
    setShowMentionPicker(false)
    setMentionTriggerIndex(-1)
    setMentionPhase("category")
    setActiveCategory(null)
  }, [])

  return {
    showMentionPicker,
    mentionItems,
    selectedMentionIndex,
    isLoadingMentions,
    mentionPhase,
    activeCategory,
    checkMentionTrigger,
    selectMentionItem,
    mentionNavUp,
    mentionNavDown,
    closeMentionPicker,
    mentionTriggerIndex,
  }
}
