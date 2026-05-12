import { defineSchema, defineTable } from 'convex/server'
import { v } from 'convex/values'

export default defineSchema({
  companies: defineTable({
    driId: v.string(),     // FastAPI company UUID (source of truth)
    name: v.string(),
    vision: v.string(),
    pitch: v.string(),
    status: v.string(),
    userId: v.string(),
    createdAt: v.string(),
  })
    .index('by_user', ['userId'])
    .index('by_dri_id', ['driId']),
})
