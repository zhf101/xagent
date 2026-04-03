"use client"

import React, { useState } from "react"
import { Plus, Trash2, ChevronRight, ChevronDown, Settings2, MoreHorizontal, Copy, Info, ListTree } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select as SelectRadix, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select-radix"
import { Switch } from "@/components/ui/switch"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

export interface SchemaNode {
  id: string
  name: string
  type: string
  description: string
  required: boolean
  defaultValue?: string
  enum?: string[]
  pattern?: string
  children?: SchemaNode[]
  route?: {
    in: "path" | "query" | "header" | "body" | "cookie"
    name?: string
    arrayStyle?: string
    objectStyle?: string
  }
}

interface SchemaTreeEditorProps {
  value: SchemaNode[]
  onChange: (value: SchemaNode[]) => void
  enableRoute?: boolean
  method?: string
}

export function SchemaTreeEditor({ value, onChange, enableRoute = true, method = "POST" }: SchemaTreeEditorProps) {
  const generateId = () => Math.random().toString(36).substring(2, 9)

  const addNode = (parentId?: string) => {
    const newNode: SchemaNode = {
      id: generateId(),
      name: "",
      type: "string",
      description: "",
      required: false,
    }

    if (!parentId) {
      onChange([...value, newNode])
    } else {
      const updateChildren = (nodes: SchemaNode[]): SchemaNode[] => {
        return nodes.map(node => {
          if (node.id === parentId) {
            return {
              ...node,
              children: [...(node.children || []), newNode],
              type: node.type === "object" ? "object" : node.type 
            }
          }
          if (node.children) {
            return { ...node, children: updateChildren(node.children) }
          }
          return node
        })
      }
      onChange(updateChildren(value))
    }
  }

  const removeNode = (id: string) => {
    const filterNodes = (nodes: SchemaNode[]): SchemaNode[] => {
      return nodes
        .filter(node => node.id !== id)
        .map(node => ({
          ...node,
          children: node.children ? filterNodes(node.children) : undefined
        }))
    }
    onChange(filterNodes(value))
  }

  const updateNode = (id: string, updates: Partial<SchemaNode>) => {
    const mapNodes = (nodes: SchemaNode[]): SchemaNode[] => {
      return nodes.map(node => {
        if (node.id === id) {
          const updatedNode = { ...node, ...updates }
          if (updates.type === "object" && !updatedNode.children) {
            updatedNode.children = []
          }
          return updatedNode
        }
        if (node.children) {
          return { ...node, children: mapNodes(node.children) }
        }
        return node
      })
    }
    onChange(mapNodes(value))
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="px-2 py-0.5 text-[10px] font-bold bg-primary/10 text-primary">VISUAL CONFIG</Badge>
          <span className="text-xs text-muted-foreground italic">支持拖拽排序与无限嵌套</span>
        </div>
        <Button variant="outline" size="sm" className="h-8 text-xs border-dashed" onClick={() => addNode()}>
          <Plus className="w-3.5 h-3.5 mr-1.5 text-primary" /> 添加根节点
        </Button>
      </div>

      <div className="rounded-2xl border border-border/60 bg-background/50 overflow-hidden shadow-sm">
        <div className="grid grid-cols-12 gap-4 p-4 bg-muted/30 border-b text-[10px] font-black uppercase tracking-widest text-muted-foreground/70">
          <div className="col-span-4">参数路径 / 字段名称</div>
          <div className="col-span-4">描述说明 / 约束 / 默认值</div>
          <div className="col-span-1 text-center">必填</div>
          <div className="col-span-3 text-right">配置与操作</div>
        </div>
        <div className="divide-y divide-border/40">
          {value.length === 0 ? (
            <div className="p-16 text-center text-sm text-muted-foreground flex flex-col items-center gap-3">
              <div className="w-12 h-12 rounded-full bg-muted/50 flex items-center justify-center">
                <ListTree className="w-6 h-6 text-muted-foreground/30" />
              </div>
              <span>点击按钮定义第一个接口参数</span>
            </div>
          ) : (
            value.map(node => (
              <NodeRow 
                key={node.id} 
                node={node} 
                depth={0} 
                onUpdate={updateNode} 
                onRemove={removeNode} 
                onAddChild={addNode}
                enableRoute={enableRoute}
                method={method}
              />
            ))
          )}
        </div>
      </div>
    </div>
  )
}

interface NodeRowProps {
  node: SchemaNode
  depth: number
  onUpdate: (id: string, updates: Partial<SchemaNode>) => void
  onRemove: (id: string) => void
  onAddChild: (parentId: string) => void
  enableRoute: boolean
  method: string
}

function NodeRow({ node, depth, onUpdate, onRemove, onAddChild, enableRoute, method }: NodeRowProps) {
  const [isExpanded, setIsExpanded] = useState(true)

  return (
    <>
      <div className="grid grid-cols-12 gap-4 p-4 items-center hover:bg-zinc-50/80 dark:hover:bg-zinc-900/50 transition-all group">
        {/* Name & Type */}
        <div className="col-span-4 flex items-start gap-2" style={{ paddingLeft: `${depth * 24}px` }}>
          {node.type === "object" || (node.children && node.children.length > 0) ? (
            <button onClick={() => setIsExpanded(!isExpanded)} className="mt-1.5 p-1 hover:bg-muted rounded-md transition-colors">
              {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            </button>
          ) : (
            <div className="w-6" />
          )}
          <div className="flex flex-col gap-2 flex-1">
            <Input 
              value={node.name} 
              onChange={e => onUpdate(node.id, { name: e.target.value })}
              placeholder="field_key"
              className="h-9 text-xs font-mono bg-background focus-visible:ring-1"
            />
            <SelectRadix value={node.type} onValueChange={v => onUpdate(node.id, { type: v })}>
              <SelectTrigger className="h-7 text-[9px] font-bold uppercase tracking-wider bg-muted/40 border-none px-2 rounded-md"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="string">STRING</SelectItem>
                <SelectItem value="number">NUMBER</SelectItem>
                <SelectItem value="integer">INTEGER</SelectItem>
                <SelectItem value="boolean">BOOLEAN</SelectItem>
                <SelectItem value="object">OBJECT (STRUCT)</SelectItem>
                <SelectItem value="array">ARRAY (LIST)</SelectItem>
              </SelectContent>
            </SelectRadix>
          </div>
        </div>

        {/* Description & Constraints */}
        <div className="col-span-4 flex flex-col gap-2">
          <Input 
            value={node.description} 
            onChange={e => onUpdate(node.id, { description: e.target.value })}
            placeholder="参数业务含义描述"
            className="h-9 text-xs"
          />
          <div className="flex items-center gap-2 overflow-hidden">
            <Input 
              value={node.defaultValue || ""} 
              onChange={e => onUpdate(node.id, { defaultValue: e.target.value })}
              placeholder="默认值"
              className="h-7 text-[10px] bg-muted/20 border-dashed"
            />
            {(node.enum?.length || 0) > 0 && <Badge variant="outline" className="text-[8px] h-5 px-1 bg-amber-500/5 text-amber-600 border-amber-500/20">ENUM</Badge>}
            {node.pattern && <Badge variant="outline" className="text-[8px] h-5 px-1 bg-blue-500/5 text-blue-600 border-blue-500/20">REGEX</Badge>}
          </div>
        </div>

        {/* Required */}
        <div className="col-span-1 flex justify-center">
          <Switch 
            checked={node.required} 
            onCheckedChange={v => onUpdate(node.id, { required: v })}
            className="scale-75 data-[state=checked]:bg-primary"
          />
        </div>

        {/* Actions */}
        <div className="col-span-3 flex justify-end gap-2">
          {enableRoute && (
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="icon" className="h-9 w-9 rounded-xl hover:bg-primary/5 hover:text-primary transition-colors">
                  <Settings2 className="w-4 h-4" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-80 p-5 shadow-2xl rounded-2xl border-border/40" align="end">
                <div className="space-y-5">
                  <div className="flex items-center justify-between border-b border-border/40 pb-3">
                    <h4 className="font-black text-[11px] uppercase tracking-widest text-muted-foreground">路由映射 (Route Map)</h4>
                    <Badge className="text-[9px] font-mono">{node.name || "UNNAMED"}</Badge>
                  </div>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">参数位置 (Inject In)</Label>
                      <SelectRadix 
                        value={node.route?.in || "query"} 
                        onValueChange={v => onUpdate(node.id, { route: { ...(node.route || { in: "query" }), in: v as any } })}
                      >
                        <SelectTrigger className="h-10 text-xs bg-zinc-50 dark:bg-zinc-900 border-none"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="query">Query (URL Params)</SelectItem>
                          <SelectItem value="header">Headers (Request)</SelectItem>
                          <SelectItem value="path">Path (URL Variable)</SelectItem>
                          {method !== "GET" && <SelectItem value="body">Body (JSON Root)</SelectItem>}
                          <SelectItem value="cookie">Cookie</SelectItem>
                        </SelectContent>
                      </SelectRadix>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">目标键名 (Alias Mapper)</Label>
                      <Input 
                        value={node.route?.name || ""} 
                        onChange={e => onUpdate(node.id, { route: { ...(node.route || { in: "query" }), name: e.target.value } })}
                        placeholder="留空默认使用参数名称"
                        className="h-10 text-xs"
                      />
                    </div>
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          )}

          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="icon" className="h-9 w-9 rounded-xl">
                <MoreHorizontal className="w-4 h-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-72 p-4 shadow-2xl rounded-2xl" align="end">
              <div className="space-y-5">
                <div className="space-y-3">
                  <Label className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">高级约束 (Constraints)</Label>
                  <div className="space-y-3">
                    <div className="space-y-1.5">
                      <span className="text-[10px] font-bold text-zinc-500 flex items-center gap-1.5"><Copy className="w-3 h-3"/> 枚举范围 (逗号分隔)</span>
                      <Input 
                        value={node.enum?.join(",") || ""} 
                        onChange={e => onUpdate(node.id, { enum: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })}
                        placeholder="例如: male, female"
                        className="h-9 text-xs"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <span className="text-[10px] font-bold text-zinc-500 flex items-center gap-1.5"><Info className="w-3 h-3"/> 正则表达式 (Pattern)</span>
                      <Input 
                        value={node.pattern || ""} 
                        onChange={e => onUpdate(node.id, { pattern: e.target.value })}
                        placeholder="例如: ^[a-z]+$"
                        className="h-9 text-xs font-mono"
                      />
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 pt-4 border-t border-border/40">
                  {node.type === "object" && (
                    <Button variant="secondary" size="sm" className="h-8 text-[10px] font-bold rounded-lg" onClick={() => onAddChild(node.id)}>
                      <Plus className="w-3 h-3 mr-1.5" /> 添加子节点
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" className="h-8 text-[10px] font-bold rounded-lg text-destructive hover:bg-destructive/10" onClick={() => onRemove(node.id)}>
                    <Trash2 className="w-3 h-3 mr-1.5" /> 删除该节点
                  </Button>
                </div>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>
      {node.type === "object" && isExpanded && node.children && node.children.map(child => (
        <NodeRow 
          key={child.id} 
          node={child} 
          depth={depth + 1} 
          onUpdate={onUpdate} 
          onRemove={onRemove} 
          onAddChild={onAddChild}
          enableRoute={enableRoute}
          method={method}
        />
      ))}
    </>
  )
}
