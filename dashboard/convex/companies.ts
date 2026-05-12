import { mutation, query } from './_generated/server'
import { v } from 'convex/values'

export const list = query({
  args: { userId: v.string() },
  handler: async (ctx, { userId }) => {
    return ctx.db
      .query('companies')
      .withIndex('by_user', q => q.eq('userId', userId))
      .order('desc')
      .collect()
  },
})

export const upsert = mutation({
  args: {
    driId: v.string(),
    name: v.string(),
    vision: v.string(),
    pitch: v.string(),
    status: v.string(),
    userId: v.string(),
    createdAt: v.string(),
  },
  handler: async (ctx, company) => {
    const existing = await ctx.db
      .query('companies')
      .withIndex('by_dri_id', q => q.eq('driId', company.driId))
      .first()
    if (existing) {
      await ctx.db.patch(existing._id, company)
    } else {
      await ctx.db.insert('companies', company)
    }
  },
})

export const remove = mutation({
  args: { driId: v.string() },
  handler: async (ctx, { driId }) => {
    const existing = await ctx.db
      .query('companies')
      .withIndex('by_dri_id', q => q.eq('driId', driId))
      .first()
    if (existing) {
      await ctx.db.delete(existing._id)
    }
  },
})
