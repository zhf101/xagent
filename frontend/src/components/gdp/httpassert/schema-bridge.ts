import { SchemaNode } from "./schema-tree-editor"

export function buildSchemaAndRoutesFromTree(tree: SchemaNode[]) {
  const inputSchema: any = {
    type: "object",
    properties: {},
    required: [],
  }
  const argsPosition: Record<string, any> = {}

  function walk(nodes: SchemaNode[], parentPath: string = "") {
    const properties: any = {}
    const required: string[] = []

    nodes.forEach(node => {
      const currentPath = parentPath ? `${parentPath}.${node.name}` : node.name
      
      const schema: any = {
        type: node.type,
        description: node.description,
      }

      if (node.defaultValue) schema.default = node.defaultValue
      if (node.enum && node.enum.length > 0) schema.enum = node.enum
      if (node.pattern) schema.pattern = node.pattern

      if (node.type === "object" && node.children) {
        const result = walk(node.children, currentPath)
        schema.properties = result.properties
        if (result.required.length > 0) {
          schema.required = result.required
        }
      } else if (node.type === "array" && node.children && node.children.length > 0) {
        const result = walk([node.children[0]], currentPath + "[0]")
        schema.items = result.properties[node.children[0].name]
      }

      properties[node.name] = schema
      if (node.required) {
        required.push(node.name)
      }

      if (node.route) {
        argsPosition[currentPath] = node.route
      }
    })

    return { properties, required }
  }

  const result = walk(tree)
  inputSchema.properties = result.properties
  inputSchema.required = result.required

  return { inputSchema, argsPosition }
}

export function parseTreeFromSchemaAndRoutes(inputSchema: any, argsPosition: Record<string, any>): SchemaNode[] {
  if (!inputSchema || inputSchema.type !== "object" || !inputSchema.properties) {
    return []
  }

  function generateId() {
    return Math.random().toString(36).substring(2, 9)
  }

  function walk(properties: any, requiredList: string[], parentPath: string = ""): SchemaNode[] {
    return Object.entries(properties).map(([name, schema]: [string, any]) => {
      const currentPath = parentPath ? `${parentPath}.${name}` : name
      const node: SchemaNode = {
        id: generateId(),
        name,
        type: schema.type || "string",
        description: schema.description || "",
        required: requiredList.includes(name),
        defaultValue: schema.default !== undefined ? String(schema.default) : undefined,
        enum: Array.isArray(schema.enum) ? schema.enum.map((v: any) => String(v)) : undefined,
        pattern: schema.pattern,
      }

      if (schema.type === "object" && schema.properties) {
        node.children = walk(schema.properties, schema.required || [], currentPath)
      } else if (schema.type === "array" && schema.items) {
        node.children = walk({ "item": schema.items }, [], currentPath)
      }

      if (argsPosition[currentPath]) {
        node.route = argsPosition[currentPath]
      }

      return node
    })
  }

  return walk(inputSchema.properties, inputSchema.required || [])
}
