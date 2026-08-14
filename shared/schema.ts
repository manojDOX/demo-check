import { sql, relations } from "drizzle-orm";
import { pgTable, text, varchar, integer, serial, timestamp, boolean, jsonb } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod";

// Re-export chat models for AI integrations
export * from "./models/chat";

// Re-export auth models (users & sessions tables)
export * from "./models/auth";

// Import users for relations
import { users } from "./models/auth";

// ============================================================
// Team Members (Collaborators)
// ============================================================

export const teamMembers = pgTable("team_members", {
  id: serial("id").primaryKey(),
  adminUserId: varchar("admin_user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  email: varchar("email").notNull(),
  role: text("role").notNull().default("viewer"),
  status: text("status").notNull().default("pending"),
  userId: varchar("user_id").references(() => users.id, { onDelete: "set null" }),
  shareToken: varchar("share_token").unique(),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const insertTeamMemberSchema = createInsertSchema(teamMembers).omit({
  id: true,
  createdAt: true,
});

export type InsertTeamMember = z.infer<typeof insertTeamMemberSchema>;
export type TeamMember = typeof teamMembers.$inferSelect;

// ============================================================
// Team Member - Client Access (Junction Table)
// ============================================================

export const teamMemberClients = pgTable("team_member_clients", {
  id: serial("id").primaryKey(),
  teamMemberId: integer("team_member_id").notNull().references(() => teamMembers.id, { onDelete: "cascade" }),
  clientId: integer("client_id").notNull().references(() => clients.id, { onDelete: "cascade" }),
});

export const insertTeamMemberClientSchema = createInsertSchema(teamMemberClients).omit({
  id: true,
});

export type InsertTeamMemberClient = z.infer<typeof insertTeamMemberClientSchema>;
export type TeamMemberClient = typeof teamMemberClients.$inferSelect;

// Relations for team tables (declared after both tables to avoid TDZ)
export const teamMembersRelations = relations(teamMembers, ({ one, many }) => ({
  admin: one(users, {
    fields: [teamMembers.adminUserId],
    references: [users.id],
    relationName: "adminTeamMembers",
  }),
  user: one(users, {
    fields: [teamMembers.userId],
    references: [users.id],
    relationName: "memberUser",
  }),
  assignedClients: many(teamMemberClients),
}));

export const teamMemberClientsRelations = relations(teamMemberClients, ({ one }) => ({
  teamMember: one(teamMembers, {
    fields: [teamMemberClients.teamMemberId],
    references: [teamMembers.id],
  }),
  client: one(clients, {
    fields: [teamMemberClients.clientId],
    references: [clients.id],
  }),
}));

// ============================================================
// BigQuery Connections
// ============================================================

export const bigqueryConnections = pgTable("bigquery_connections", {
  id: serial("id").primaryKey(),
  userId: varchar("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  name: text("name").notNull(),
  projectId: text("project_id").notNull(),
  datasetId: text("dataset_id"),
  credentials: text("credentials").notNull(),
  isActive: boolean("is_active").default(true),
  lastTestedAt: timestamp("last_tested_at"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const bigqueryConnectionsRelations = relations(bigqueryConnections, ({ one, many }) => ({
  user: one(users, {
    fields: [bigqueryConnections.userId],
    references: [users.id],
  }),
  clients: many(clients),
}));

export const insertBigQueryConnectionSchema = createInsertSchema(bigqueryConnections).omit({
  id: true,
  createdAt: true,
  lastTestedAt: true,
});

export type InsertBigQueryConnection = z.infer<typeof insertBigQueryConnectionSchema>;
export type BigQueryConnection = typeof bigqueryConnections.$inferSelect;

// ============================================================
// Connection Schemas (Discovered Tables/Columns)
// ============================================================

export const connectionSchemas = pgTable("connection_schemas", {
  id: serial("id").primaryKey(),
  connectionId: integer("connection_id").notNull().references(() => bigqueryConnections.id, { onDelete: "cascade" }),
  datasetName: text("dataset_name").notNull(),
  tableName: text("table_name").notNull(),
  columnName: text("column_name").notNull(),
  dataType: text("data_type").notNull(),
  isNullable: boolean("is_nullable").default(true),
  description: text("description"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
  updatedAt: timestamp("updated_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const connectionSchemasRelations = relations(connectionSchemas, ({ one }) => ({
  connection: one(bigqueryConnections, {
    fields: [connectionSchemas.connectionId],
    references: [bigqueryConnections.id],
  }),
}));

export const insertConnectionSchemaSchema = createInsertSchema(connectionSchemas).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertConnectionSchema = z.infer<typeof insertConnectionSchemaSchema>;
export type ConnectionSchema = typeof connectionSchemas.$inferSelect;

// ============================================================
// Retail Clients
// ============================================================

export const clients = pgTable("clients", {
  id: serial("id").primaryKey(),
  userId: varchar("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  connectionId: integer("connection_id").references(() => bigqueryConnections.id, { onDelete: "set null" }),
  name: text("name").notNull(),
  industry: text("industry").default("retail"),
  logoUrl: text("logo_url"),
  primaryColor: text("primary_color").default("#3B82F6"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const clientsRelations = relations(clients, ({ one, many }) => ({
  user: one(users, {
    fields: [clients.userId],
    references: [users.id],
  }),
  connection: one(bigqueryConnections, {
    fields: [clients.connectionId],
    references: [bigqueryConnections.id],
  }),
  segments: many(segments),
  queries: many(queries),
}));

export const insertClientSchema = createInsertSchema(clients).omit({
  id: true,
  createdAt: true,
});

export type InsertClient = z.infer<typeof insertClientSchema>;
export type Client = typeof clients.$inferSelect;

// ============================================================
// Business Profiles (per Client)
// ============================================================

export const businessProfiles = pgTable("business_profiles", {
  id: serial("id").primaryKey(),
  clientId: integer("client_id").notNull().references(() => clients.id, { onDelete: "cascade" }).unique(),
  description: text("description"),
  targetAudience: text("target_audience"),
  additionalInfo: text("additional_info"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
  updatedAt: timestamp("updated_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const businessProfilesRelations = relations(businessProfiles, ({ one }) => ({
  client: one(clients, {
    fields: [businessProfiles.clientId],
    references: [clients.id],
  }),
}));

export const insertBusinessProfileSchema = createInsertSchema(businessProfiles).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertBusinessProfile = z.infer<typeof insertBusinessProfileSchema>;
export type BusinessProfile = typeof businessProfiles.$inferSelect;

// ============================================================
// Product Catalog (per Client)
// ============================================================

export const productCatalog = pgTable("product_catalog", {
  id: serial("id").primaryKey(),
  clientId: integer("client_id").notNull().references(() => clients.id, { onDelete: "cascade" }),
  name: text("name").notNull(),
  description: text("description"),
  benefits: text("benefits"),
  cost: text("cost"),
  price: text("price"),
  category: text("category"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const productCatalogRelations = relations(productCatalog, ({ one }) => ({
  client: one(clients, {
    fields: [productCatalog.clientId],
    references: [clients.id],
  }),
}));

export const insertProductCatalogSchema = createInsertSchema(productCatalog).omit({
  id: true,
  createdAt: true,
});

export type InsertProductCatalog = z.infer<typeof insertProductCatalogSchema>;
export type ProductCatalogItem = typeof productCatalog.$inferSelect;

// ============================================================
// Customer Segments
// ============================================================

export const segments = pgTable("segments", {
  id: serial("id").primaryKey(),
  userId: varchar("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  clientId: integer("client_id").references(() => clients.id, { onDelete: "cascade" }),
  name: text("name").notNull(),
  description: text("description"),
  criteria: jsonb("criteria").notNull().default({}),
  contactCount: integer("contact_count").default(0),
  isAiGenerated: boolean("is_ai_generated").default(false),
  status: text("status").default("active"),
  generatedSql: text("generated_sql"),
  memberData: jsonb("member_data"),
  lastSyncedAt: timestamp("last_synced_at"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const segmentsRelations = relations(segments, ({ one }) => ({
  user: one(users, {
    fields: [segments.userId],
    references: [users.id],
  }),
  client: one(clients, {
    fields: [segments.clientId],
    references: [clients.id],
  }),
}));

export const insertSegmentSchema = createInsertSchema(segments).omit({
  id: true,
  createdAt: true,
  lastSyncedAt: true,
});

export type InsertSegment = z.infer<typeof insertSegmentSchema>;
export type Segment = typeof segments.$inferSelect;

// ============================================================
// Query History
// ============================================================

export const queries = pgTable("queries", {
  id: serial("id").primaryKey(),
  userId: varchar("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  clientId: integer("client_id").references(() => clients.id, { onDelete: "set null" }),
  naturalLanguage: text("natural_language").notNull(),
  generatedSql: text("generated_sql"),
  resultSummary: text("result_summary"),
  resultData: jsonb("result_data"),
  visualizationType: text("visualization_type"),
  isSaved: boolean("is_saved").default(false),
  isRecommendation: boolean("is_recommendation").default(false),
  recommendationText: text("recommendation_text"),
  executionTimeMs: integer("execution_time_ms"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const queriesRelations = relations(queries, ({ one }) => ({
  user: one(users, {
    fields: [queries.userId],
    references: [users.id],
  }),
  client: one(clients, {
    fields: [queries.clientId],
    references: [clients.id],
  }),
}));

export const insertQuerySchema = createInsertSchema(queries).omit({
  id: true,
  createdAt: true,
});

export type InsertQuery = z.infer<typeof insertQuerySchema>;
export type Query = typeof queries.$inferSelect;

// ============================================================
// Pre-computed KPIs (Daily Snapshots)
// ============================================================

export const kpiSnapshots = pgTable("kpi_snapshots", {
  id: serial("id").primaryKey(),
  clientId: integer("client_id").notNull().references(() => clients.id, { onDelete: "cascade" }),
  date: timestamp("date").notNull(),
  totalSales: text("total_sales"),
  orderCount: integer("order_count"),
  averageOrderValue: text("average_order_value"),
  recurrenceRate: text("recurrence_rate"),
  newCustomers: integer("new_customers"),
  recurringCustomers: integer("recurring_customers"),
  cartAbandonmentRate: text("cart_abandonment_rate"),
  customerLifetimeValue: text("customer_lifetime_value"),
  returnRate: text("return_rate"),
  inventoryTurnover: text("inventory_turnover"),
  rawData: jsonb("raw_data"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const kpiSnapshotsRelations = relations(kpiSnapshots, ({ one }) => ({
  client: one(clients, {
    fields: [kpiSnapshots.clientId],
    references: [clients.id],
  }),
}));

export const insertKpiSnapshotSchema = createInsertSchema(kpiSnapshots).omit({
  id: true,
  createdAt: true,
});

export type InsertKpiSnapshot = z.infer<typeof insertKpiSnapshotSchema>;
export type KpiSnapshot = typeof kpiSnapshots.$inferSelect;

// ============================================================
// GoHighLevel Export History
// ============================================================

export const ghlExports = pgTable("ghl_exports", {
  id: serial("id").primaryKey(),
  userId: varchar("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  segmentId: integer("segment_id").references(() => segments.id, { onDelete: "set null" }),
  contactCount: integer("contact_count").notNull(),
  status: text("status").default("pending"),
  ghlLocationId: text("ghl_location_id"),
  ghlTags: text("ghl_tags").array(),
  errorMessage: text("error_message"),
  completedAt: timestamp("completed_at"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const ghlExportsRelations = relations(ghlExports, ({ one }) => ({
  user: one(users, {
    fields: [ghlExports.userId],
    references: [users.id],
  }),
  segment: one(segments, {
    fields: [ghlExports.segmentId],
    references: [segments.id],
  }),
}));

export const insertGhlExportSchema = createInsertSchema(ghlExports).omit({
  id: true,
  createdAt: true,
  completedAt: true,
});

export type InsertGhlExport = z.infer<typeof insertGhlExportSchema>;
export type GhlExport = typeof ghlExports.$inferSelect;

// ============================================================
// Dynamic Persona - Page Designs
// ============================================================

export const pageDesigns = pgTable("page_designs", {
  id: serial("id").primaryKey(),
  userId: varchar("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  clientId: integer("client_id").references(() => clients.id, { onDelete: "cascade" }),
  name: text("name").notNull(),
  slug: text("slug").notNull(),
  isPublished: boolean("is_published").default(false),
  publishedVersionId: integer("published_version_id"),
  publishedAt: timestamp("published_at"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
  updatedAt: timestamp("updated_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const insertPageDesignSchema = createInsertSchema(pageDesigns).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
  publishedAt: true,
  publishedVersionId: true,
});

export type InsertPageDesign = z.infer<typeof insertPageDesignSchema>;
export type PageDesign = typeof pageDesigns.$inferSelect;

// ============================================================
// Dynamic Persona - Page Versions
// ============================================================

export const pageVersions = pgTable("page_versions", {
  id: serial("id").primaryKey(),
  pageId: integer("page_id").notNull().references(() => pageDesigns.id, { onDelete: "cascade" }),
  versionName: text("version_name").notNull(),
  versionNumber: integer("version_number").notNull().default(1),
  isActive: boolean("is_active").default(false),
  htmlContent: text("html_content"),
  cssContent: text("css_content"),
  gjsComponents: jsonb("gjs_components"),
  gjsStyles: jsonb("gjs_styles"),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const insertPageVersionSchema = createInsertSchema(pageVersions).omit({
  id: true,
  createdAt: true,
});

export type InsertPageVersion = z.infer<typeof insertPageVersionSchema>;
export type PageVersion = typeof pageVersions.$inferSelect;

// ============================================================
// Dynamic Persona - Page Sections
// ============================================================

export const pageSections = pgTable("page_sections", {
  id: serial("id").primaryKey(),
  versionId: integer("version_id").notNull().references(() => pageVersions.id, { onDelete: "cascade" }),
  sectionType: text("section_type").notNull(),
  sectionOrder: integer("section_order").notNull().default(0),
  content: jsonb("content").notNull().default({}),
  styles: jsonb("styles").notNull().default({}),
  isVisible: boolean("is_visible").default(true),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
  updatedAt: timestamp("updated_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const insertPageSectionSchema = createInsertSchema(pageSections).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertPageSection = z.infer<typeof insertPageSectionSchema>;
export type PageSection = typeof pageSections.$inferSelect;

// ============================================================
// Dynamic Persona - Section Templates
// ============================================================

export const sectionTemplates = pgTable("section_templates", {
  id: serial("id").primaryKey(),
  userId: varchar("user_id").references(() => users.id, { onDelete: "cascade" }),
  name: text("name").notNull(),
  sectionType: text("section_type").notNull(),
  content: jsonb("content").notNull().default({}),
  styles: jsonb("styles").notNull().default({}),
  thumbnailUrl: text("thumbnail_url"),
  isSystem: boolean("is_system").default(false),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const insertSectionTemplateSchema = createInsertSchema(sectionTemplates).omit({
  id: true,
  createdAt: true,
});

export type InsertSectionTemplate = z.infer<typeof insertSectionTemplateSchema>;
export type SectionTemplate = typeof sectionTemplates.$inferSelect;

// Relations for page builder
export const pageDesignsRelations = relations(pageDesigns, ({ one, many }) => ({
  user: one(users, {
    fields: [pageDesigns.userId],
    references: [users.id],
  }),
  client: one(clients, {
    fields: [pageDesigns.clientId],
    references: [clients.id],
  }),
  versions: many(pageVersions),
  personalizationZones: many(personalizationZones),
}));

export const pageVersionsRelations = relations(pageVersions, ({ one, many }) => ({
  page: one(pageDesigns, {
    fields: [pageVersions.pageId],
    references: [pageDesigns.id],
  }),
  sections: many(pageSections),
}));

export const pageSectionsRelations = relations(pageSections, ({ one }) => ({
  version: one(pageVersions, {
    fields: [pageSections.versionId],
    references: [pageVersions.id],
  }),
}));

export const sectionTemplatesRelations = relations(sectionTemplates, ({ one }) => ({
  user: one(users, {
    fields: [sectionTemplates.userId],
    references: [users.id],
  }),
}));

// ============================================================
// Dynamic Persona - Personalization Zones
// ============================================================

export const personalizationZones = pgTable("personalization_zones", {
  id: serial("id").primaryKey(),
  pageDesignId: integer("page_design_id").notNull().references(() => pageDesigns.id, { onDelete: "cascade" }),
  zoneId: text("zone_id").notNull(),
  zoneName: text("zone_name").notNull(),
  zoneType: text("zone_type").default("static"),
  segmentId: integer("segment_id").references(() => segments.id, { onDelete: "set null" }),
  contentConfig: jsonb("content_config").default({}),
  fallbackContent: jsonb("fallback_content").default({}),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const personalizationZonesRelations = relations(personalizationZones, ({ one }) => ({
  pageDesign: one(pageDesigns, {
    fields: [personalizationZones.pageDesignId],
    references: [pageDesigns.id],
  }),
  segment: one(segments, {
    fields: [personalizationZones.segmentId],
    references: [segments.id],
  }),
}));

export const insertPersonalizationZoneSchema = createInsertSchema(personalizationZones).omit({
  id: true,
  createdAt: true,
});

export type InsertPersonalizationZone = z.infer<typeof insertPersonalizationZoneSchema>;
export type PersonalizationZone = typeof personalizationZones.$inferSelect;

// ============================================================
// Dynamic Persona - Anonymous Visitors
// ============================================================

export const anonymousVisitors = pgTable("anonymous_visitors", {
  id: serial("id").primaryKey(),
  fingerprintId: text("fingerprint_id").notNull().unique(),
  clientId: integer("client_id").references(() => clients.id, { onDelete: "cascade" }),
  firstVisitAt: timestamp("first_visit_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
  lastVisitAt: timestamp("last_visit_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
  visitCount: integer("visit_count").default(1),
  deviceInfo: jsonb("device_info").default({}),
  referralSource: text("referral_source"),
  behavioralSegmentId: integer("behavioral_segment_id").references(() => segments.id, { onDelete: "set null" }),
});

export const anonymousVisitorsRelations = relations(anonymousVisitors, ({ one, many }) => ({
  client: one(clients, {
    fields: [anonymousVisitors.clientId],
    references: [clients.id],
  }),
  behavioralSegment: one(segments, {
    fields: [anonymousVisitors.behavioralSegmentId],
    references: [segments.id],
  }),
  navigationEvents: many(navigationEvents),
}));

export const insertAnonymousVisitorSchema = createInsertSchema(anonymousVisitors).omit({
  id: true,
});

export type InsertAnonymousVisitor = z.infer<typeof insertAnonymousVisitorSchema>;
export type AnonymousVisitor = typeof anonymousVisitors.$inferSelect;

// ============================================================
// Dynamic Persona - Navigation Events
// ============================================================

export const navigationEvents = pgTable("navigation_events", {
  id: serial("id").primaryKey(),
  visitorId: integer("visitor_id").notNull().references(() => anonymousVisitors.id, { onDelete: "cascade" }),
  eventType: text("event_type").notNull(),
  pageUrl: text("page_url"),
  elementId: text("element_id"),
  eventData: jsonb("event_data").default({}),
  timestamp: timestamp("timestamp").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const navigationEventsRelations = relations(navigationEvents, ({ one }) => ({
  visitor: one(anonymousVisitors, {
    fields: [navigationEvents.visitorId],
    references: [anonymousVisitors.id],
  }),
}));

export const insertNavigationEventSchema = createInsertSchema(navigationEvents).omit({
  id: true,
});

export type InsertNavigationEvent = z.infer<typeof insertNavigationEventSchema>;
export type NavigationEvent = typeof navigationEvents.$inferSelect;

// ============================================================
// Content Library
// ============================================================

export const contentLibrary = pgTable("content_library", {
  id: serial("id").primaryKey(),
  userId: varchar("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  clientId: integer("client_id").references(() => clients.id, { onDelete: "cascade" }),
  contentType: text("content_type").notNull(),
  title: text("title").notNull(),
  content: jsonb("content").notNull().default({}),
  segmentTags: text("segment_tags").array(),
  isActive: boolean("is_active").default(true),
  createdAt: timestamp("created_at").default(sql`CURRENT_TIMESTAMP`).notNull(),
});

export const contentLibraryRelations = relations(contentLibrary, ({ one }) => ({
  user: one(users, {
    fields: [contentLibrary.userId],
    references: [users.id],
  }),
  client: one(clients, {
    fields: [contentLibrary.clientId],
    references: [clients.id],
  }),
}));

export const insertContentLibrarySchema = createInsertSchema(contentLibrary).omit({
  id: true,
  createdAt: true,
});

export type InsertContentLibrary = z.infer<typeof insertContentLibrarySchema>;
export type ContentLibrary = typeof contentLibrary.$inferSelect;
