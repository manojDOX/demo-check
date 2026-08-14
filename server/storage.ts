import { db } from "./db";
import { eq, desc, and, sql } from "drizzle-orm";
import {
  users,
  bigqueryConnections,
  connectionSchemas,
  clients,
  segments,
  queries,
  kpiSnapshots,
  ghlExports,
  pageDesigns,
  pageVersions,
  pageSections,
  sectionTemplates,
  personalizationZones,
  anonymousVisitors,
  navigationEvents,
  contentLibrary,
  teamMembers,
  teamMemberClients,
  businessProfiles,
  productCatalog,
  type User,
  type UpsertUser,
  type BigQueryConnection,
  type InsertBigQueryConnection,
  type ConnectionSchema,
  type InsertConnectionSchema,
  type Client,
  type InsertClient,
  type Segment,
  type InsertSegment,
  type Query,
  type InsertQuery,
  type KpiSnapshot,
  type InsertKpiSnapshot,
  type GhlExport,
  type InsertGhlExport,
  type PageDesign,
  type InsertPageDesign,
  type PageVersion,
  type InsertPageVersion,
  type PageSection,
  type InsertPageSection,
  type SectionTemplate,
  type InsertSectionTemplate,
  type TeamMember,
  type InsertTeamMember,
  type TeamMemberClient,
  type InsertTeamMemberClient,
  type BusinessProfile,
  type InsertBusinessProfile,
  type ProductCatalogItem,
  type InsertProductCatalog,
} from "@shared/schema";

export interface IStorage {
  getUser(id: string): Promise<User | undefined>;
  getUserByEmail(email: string): Promise<User | undefined>;
  createUser(user: UpsertUser): Promise<User>;
  updateUser(id: string, data: Partial<User>): Promise<User | undefined>;

  getConnections(userId: string): Promise<BigQueryConnection[]>;
  getConnection(id: number): Promise<BigQueryConnection | undefined>;
  getConnectionByClientId(clientId: number): Promise<BigQueryConnection | undefined>;
  createConnection(connection: InsertBigQueryConnection): Promise<BigQueryConnection>;
  updateConnection(id: number, data: Partial<BigQueryConnection>): Promise<BigQueryConnection | undefined>;
  deleteConnection(id: number): Promise<void>;

  getConnectionSchemas(connectionId: number): Promise<ConnectionSchema[]>;
  createConnectionSchema(schema: InsertConnectionSchema): Promise<ConnectionSchema>;
  deleteConnectionSchemas(connectionId: number): Promise<void>;

  getClients(userId: string): Promise<Client[]>;
  getClient(id: number): Promise<Client | undefined>;
  createClient(client: InsertClient): Promise<Client>;
  updateClient(id: number, data: Partial<Client>): Promise<Client | undefined>;
  deleteClient(id: number): Promise<void>;

  getSegments(userId: string, clientId?: number): Promise<Segment[]>;
  getSegment(id: number): Promise<Segment | undefined>;
  createSegment(segment: InsertSegment): Promise<Segment>;
  updateSegment(id: number, data: Partial<Segment>): Promise<Segment | undefined>;
  deleteSegment(id: number): Promise<void>;

  getQueries(userId: string, limit?: number): Promise<Query[]>;
  getSavedQueries(userId: string, limit?: number): Promise<Query[]>;
  getQuery(id: number): Promise<Query | undefined>;
  createQuery(query: InsertQuery): Promise<Query>;
  updateQuery(id: number, data: Partial<Query>): Promise<Query | undefined>;
  deleteQuery(id: number): Promise<boolean>;

  getKpiSnapshots(clientId: number, days?: number): Promise<KpiSnapshot[]>;
  createKpiSnapshot(snapshot: InsertKpiSnapshot): Promise<KpiSnapshot>;

  getExports(userId: string): Promise<GhlExport[]>;
  createExport(ghlExport: InsertGhlExport): Promise<GhlExport>;
  updateExport(id: number, data: Partial<GhlExport>): Promise<GhlExport | undefined>;

  // Page Builder
  getPages(userId: string): Promise<PageDesign[]>;
  getPage(id: number): Promise<PageDesign | undefined>;
  createPage(page: InsertPageDesign): Promise<PageDesign>;
  updatePage(id: number, data: Partial<PageDesign>): Promise<PageDesign | undefined>;
  deletePage(id: number): Promise<void>;

  getPageVersions(pageId: number): Promise<PageVersion[]>;
  getPageVersion(id: number): Promise<PageVersion | undefined>;
  createPageVersion(version: InsertPageVersion): Promise<PageVersion>;
  updatePageVersion(id: number, data: Partial<PageVersion>): Promise<PageVersion | undefined>;
  deletePageVersion(id: number): Promise<void>;

  getPageSections(versionId: number): Promise<PageSection[]>;
  getPageSection(id: number): Promise<PageSection | undefined>;
  createPageSection(section: InsertPageSection): Promise<PageSection>;
  updatePageSection(id: number, data: Partial<PageSection>): Promise<PageSection | undefined>;
  deletePageSection(id: number): Promise<void>;
  reorderSections(versionId: number, sectionIds: number[]): Promise<void>;

  getSectionTemplates(userId?: string): Promise<SectionTemplate[]>;
  getSectionTemplate(id: number): Promise<SectionTemplate | undefined>;
  createSectionTemplate(template: InsertSectionTemplate): Promise<SectionTemplate>;
  deleteSectionTemplate(id: number): Promise<void>;

  getTeamMembers(adminUserId: string): Promise<TeamMember[]>;
  getTeamMember(id: number): Promise<TeamMember | undefined>;
  getTeamMemberByEmail(adminUserId: string, email: string): Promise<TeamMember | undefined>;
  getTeamMembershipByUserId(userId: string): Promise<TeamMember | undefined>;
  getTeamMemberByShareToken(token: string): Promise<TeamMember | undefined>;
  createTeamMember(member: InsertTeamMember): Promise<TeamMember>;
  updateTeamMember(id: number, data: Partial<TeamMember>): Promise<TeamMember | undefined>;
  deleteTeamMember(id: number): Promise<void>;

  getTeamMemberClients(teamMemberId: number): Promise<TeamMemberClient[]>;
  setTeamMemberClients(teamMemberId: number, clientIds: number[]): Promise<void>;

  getBusinessProfile(clientId: number): Promise<BusinessProfile | undefined>;
  upsertBusinessProfile(data: InsertBusinessProfile): Promise<BusinessProfile>;

  getProductCatalog(clientId: number): Promise<ProductCatalogItem[]>;
  createProductCatalogItem(item: InsertProductCatalog): Promise<ProductCatalogItem>;
  updateProductCatalogItem(id: number, data: Partial<ProductCatalogItem>): Promise<ProductCatalogItem | undefined>;
  deleteProductCatalogItem(id: number): Promise<void>;
}

export class DatabaseStorage implements IStorage {
  async getUser(id: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.id, id));
    return user;
  }

  async getUserByEmail(email: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.email, email));
    return user;
  }

  async createUser(insertUser: UpsertUser): Promise<User> {
    const [user] = await db.insert(users).values(insertUser).returning();
    return user;
  }

  async updateUser(id: string, data: Partial<User>): Promise<User | undefined> {
    const [updated] = await db.update(users).set(data).where(eq(users.id, id)).returning();
    return updated;
  }

  async getConnections(userId: string): Promise<BigQueryConnection[]> {
    return db.select().from(bigqueryConnections).where(eq(bigqueryConnections.userId, userId)).orderBy(desc(bigqueryConnections.createdAt));
  }

  async getConnection(id: number): Promise<BigQueryConnection | undefined> {
    const [connection] = await db.select().from(bigqueryConnections).where(eq(bigqueryConnections.id, id));
    return connection;
  }

  async getConnectionByClientId(clientId: number): Promise<BigQueryConnection | undefined> {
    const client = await this.getClient(clientId);
    if (!client || !client.connectionId) {
      return undefined;
    }
    return this.getConnection(client.connectionId);
  }

  async createConnection(connection: InsertBigQueryConnection): Promise<BigQueryConnection> {
    const [created] = await db.insert(bigqueryConnections).values(connection).returning();
    return created;
  }

  async updateConnection(id: number, data: Partial<BigQueryConnection>): Promise<BigQueryConnection | undefined> {
    const [updated] = await db.update(bigqueryConnections).set(data).where(eq(bigqueryConnections.id, id)).returning();
    return updated;
  }

  async deleteConnection(id: number): Promise<void> {
    await db.delete(bigqueryConnections).where(eq(bigqueryConnections.id, id));
  }

  async getConnectionSchemas(connectionId: number): Promise<ConnectionSchema[]> {
    return db.select().from(connectionSchemas).where(eq(connectionSchemas.connectionId, connectionId));
  }

  async createConnectionSchema(schema: InsertConnectionSchema): Promise<ConnectionSchema> {
    const [created] = await db.insert(connectionSchemas).values(schema).returning();
    return created;
  }

  async deleteConnectionSchemas(connectionId: number): Promise<void> {
    await db.delete(connectionSchemas).where(eq(connectionSchemas.connectionId, connectionId));
  }

  async getClients(userId: string): Promise<Client[]> {
    return db.select().from(clients).where(eq(clients.userId, userId)).orderBy(desc(clients.createdAt));
  }

  async getClient(id: number): Promise<Client | undefined> {
    const [client] = await db.select().from(clients).where(eq(clients.id, id));
    return client;
  }

  async createClient(client: InsertClient): Promise<Client> {
    const [created] = await db.insert(clients).values(client).returning();
    return created;
  }

  async updateClient(id: number, data: Partial<Client>): Promise<Client | undefined> {
    const [updated] = await db.update(clients).set(data).where(eq(clients.id, id)).returning();
    return updated;
  }

  async deleteClient(id: number): Promise<void> {
    await db.delete(clients).where(eq(clients.id, id));
  }

  async getSegments(userId: string, clientId?: number): Promise<Segment[]> {
    if (clientId) {
      return db.select().from(segments).where(and(eq(segments.userId, userId), eq(segments.clientId, clientId))).orderBy(desc(segments.createdAt));
    }
    return db.select().from(segments).where(eq(segments.userId, userId)).orderBy(desc(segments.createdAt));
  }

  async getSegment(id: number): Promise<Segment | undefined> {
    const [segment] = await db.select().from(segments).where(eq(segments.id, id));
    return segment;
  }

  async createSegment(segment: InsertSegment): Promise<Segment> {
    const [created] = await db.insert(segments).values(segment).returning();
    return created;
  }

  async updateSegment(id: number, data: Partial<Segment>): Promise<Segment | undefined> {
    const [updated] = await db.update(segments).set(data).where(eq(segments.id, id)).returning();
    return updated;
  }

  async deleteSegment(id: number): Promise<void> {
    await db.delete(segments).where(eq(segments.id, id));
  }

  async getQueries(userId: string, limit?: number): Promise<Query[]> {
    const query = db.select().from(queries).where(eq(queries.userId, userId)).orderBy(desc(queries.createdAt));
    if (limit) {
      return query.limit(limit);
    }
    return query;
  }

  async getSavedQueries(userId: string, limit?: number): Promise<Query[]> {
    const query = db.select().from(queries)
      .where(and(eq(queries.userId, userId), eq(queries.isSaved, true)))
      .orderBy(desc(queries.createdAt));
    if (limit) {
      return query.limit(limit);
    }
    return query;
  }

  async getQuery(id: number): Promise<Query | undefined> {
    const [query] = await db.select().from(queries).where(eq(queries.id, id));
    return query;
  }

  async createQuery(query: InsertQuery): Promise<Query> {
    const [created] = await db.insert(queries).values(query).returning();
    return created;
  }

  async updateQuery(id: number, data: Partial<Query>): Promise<Query | undefined> {
    const [updated] = await db.update(queries).set(data).where(eq(queries.id, id)).returning();
    return updated;
  }

  async deleteQuery(id: number): Promise<boolean> {
    const result = await db.delete(queries).where(eq(queries.id, id)).returning();
    return result.length > 0;
  }

  async getKpiSnapshots(clientId: number, days: number = 30): Promise<KpiSnapshot[]> {
    return db.select().from(kpiSnapshots).where(eq(kpiSnapshots.clientId, clientId)).orderBy(desc(kpiSnapshots.date)).limit(days);
  }

  async createKpiSnapshot(snapshot: InsertKpiSnapshot): Promise<KpiSnapshot> {
    const [created] = await db.insert(kpiSnapshots).values(snapshot).returning();
    return created;
  }

  async getExports(userId: string): Promise<GhlExport[]> {
    return db.select().from(ghlExports).where(eq(ghlExports.userId, userId)).orderBy(desc(ghlExports.createdAt));
  }

  async createExport(ghlExport: InsertGhlExport): Promise<GhlExport> {
    const [created] = await db.insert(ghlExports).values(ghlExport).returning();
    return created;
  }

  async updateExport(id: number, data: Partial<GhlExport>): Promise<GhlExport | undefined> {
    const [updated] = await db.update(ghlExports).set(data).where(eq(ghlExports.id, id)).returning();
    return updated;
  }

  // Page Builder Methods
  async getPages(userId: string): Promise<PageDesign[]> {
    return db.select().from(pageDesigns).where(eq(pageDesigns.userId, userId)).orderBy(desc(pageDesigns.updatedAt));
  }

  async getPage(id: number): Promise<PageDesign | undefined> {
    const [page] = await db.select().from(pageDesigns).where(eq(pageDesigns.id, id));
    return page;
  }

  async createPage(page: InsertPageDesign): Promise<PageDesign> {
    const [created] = await db.insert(pageDesigns).values(page).returning();
    return created;
  }

  async updatePage(id: number, data: Partial<PageDesign>): Promise<PageDesign | undefined> {
    const [updated] = await db.update(pageDesigns).set({ ...data, updatedAt: new Date() }).where(eq(pageDesigns.id, id)).returning();
    return updated;
  }

  async deletePage(id: number): Promise<void> {
    await db.delete(pageDesigns).where(eq(pageDesigns.id, id));
  }

  async getPageVersions(pageId: number): Promise<PageVersion[]> {
    return db.select().from(pageVersions).where(eq(pageVersions.pageId, pageId)).orderBy(desc(pageVersions.versionNumber));
  }

  async getPageVersion(id: number): Promise<PageVersion | undefined> {
    const [version] = await db.select().from(pageVersions).where(eq(pageVersions.id, id));
    return version;
  }

  async createPageVersion(version: InsertPageVersion): Promise<PageVersion> {
    const [created] = await db.insert(pageVersions).values(version).returning();
    return created;
  }

  async updatePageVersion(id: number, data: Partial<PageVersion>): Promise<PageVersion | undefined> {
    const [updated] = await db.update(pageVersions).set(data).where(eq(pageVersions.id, id)).returning();
    return updated;
  }

  async deletePageVersion(id: number): Promise<void> {
    await db.delete(pageVersions).where(eq(pageVersions.id, id));
  }

  async getPageSections(versionId: number): Promise<PageSection[]> {
    return db.select().from(pageSections).where(eq(pageSections.versionId, versionId)).orderBy(pageSections.sectionOrder);
  }

  async getPageSection(id: number): Promise<PageSection | undefined> {
    const [section] = await db.select().from(pageSections).where(eq(pageSections.id, id));
    return section;
  }

  async createPageSection(section: InsertPageSection): Promise<PageSection> {
    const [created] = await db.insert(pageSections).values(section).returning();
    return created;
  }

  async updatePageSection(id: number, data: Partial<PageSection>): Promise<PageSection | undefined> {
    const [updated] = await db.update(pageSections).set({ ...data, updatedAt: new Date() }).where(eq(pageSections.id, id)).returning();
    return updated;
  }

  async deletePageSection(id: number): Promise<void> {
    await db.delete(pageSections).where(eq(pageSections.id, id));
  }

  async reorderSections(versionId: number, sectionIds: number[]): Promise<void> {
    for (let i = 0; i < sectionIds.length; i++) {
      await db.update(pageSections).set({ sectionOrder: i }).where(eq(pageSections.id, sectionIds[i]));
    }
  }

  async getSectionTemplates(userId?: string): Promise<SectionTemplate[]> {
    if (userId) {
      return db.select().from(sectionTemplates)
        .where(sql`${sectionTemplates.isSystem} = true OR ${sectionTemplates.userId} = ${userId}`)
        .orderBy(sectionTemplates.sectionType);
    }
    return db.select().from(sectionTemplates).where(eq(sectionTemplates.isSystem, true)).orderBy(sectionTemplates.sectionType);
  }

  async getSectionTemplate(id: number): Promise<SectionTemplate | undefined> {
    const [template] = await db.select().from(sectionTemplates).where(eq(sectionTemplates.id, id));
    return template;
  }

  async createSectionTemplate(template: InsertSectionTemplate): Promise<SectionTemplate> {
    const [created] = await db.insert(sectionTemplates).values(template).returning();
    return created;
  }

  async deleteSectionTemplate(id: number): Promise<void> {
    await db.delete(sectionTemplates).where(eq(sectionTemplates.id, id));
  }

  async getTeamMembers(adminUserId: string): Promise<TeamMember[]> {
    return db.select().from(teamMembers).where(eq(teamMembers.adminUserId, adminUserId)).orderBy(desc(teamMembers.createdAt));
  }

  async getTeamMember(id: number): Promise<TeamMember | undefined> {
    const [member] = await db.select().from(teamMembers).where(eq(teamMembers.id, id));
    return member;
  }

  async getTeamMemberByEmail(adminUserId: string, email: string): Promise<TeamMember | undefined> {
    const [member] = await db.select().from(teamMembers).where(and(eq(teamMembers.adminUserId, adminUserId), eq(teamMembers.email, email.toLowerCase())));
    return member;
  }

  async getTeamMembershipByUserId(userId: string): Promise<TeamMember | undefined> {
    const [member] = await db.select().from(teamMembers).where(and(eq(teamMembers.userId, userId), eq(teamMembers.status, "active")));
    return member;
  }

  async getTeamMemberByShareToken(token: string): Promise<TeamMember | undefined> {
    const [member] = await db.select().from(teamMembers).where(eq(teamMembers.shareToken, token));
    return member;
  }

  async createTeamMember(member: InsertTeamMember): Promise<TeamMember> {
    const [created] = await db.insert(teamMembers).values({ ...member, email: member.email.toLowerCase() }).returning();
    return created;
  }

  async updateTeamMember(id: number, data: Partial<TeamMember>): Promise<TeamMember | undefined> {
    const [updated] = await db.update(teamMembers).set(data).where(eq(teamMembers.id, id)).returning();
    return updated;
  }

  async deleteTeamMember(id: number): Promise<void> {
    await db.delete(teamMembers).where(eq(teamMembers.id, id));
  }

  async getTeamMemberClients(teamMemberId: number): Promise<TeamMemberClient[]> {
    return db.select().from(teamMemberClients).where(eq(teamMemberClients.teamMemberId, teamMemberId));
  }

  async setTeamMemberClients(teamMemberId: number, clientIds: number[]): Promise<void> {
    await db.delete(teamMemberClients).where(eq(teamMemberClients.teamMemberId, teamMemberId));
    if (clientIds.length > 0) {
      await db.insert(teamMemberClients).values(clientIds.map(clientId => ({ teamMemberId, clientId })));
    }
  }

  async getBusinessProfile(clientId: number): Promise<BusinessProfile | undefined> {
    const [profile] = await db.select().from(businessProfiles).where(eq(businessProfiles.clientId, clientId));
    return profile;
  }

  async upsertBusinessProfile(data: InsertBusinessProfile): Promise<BusinessProfile> {
    const existing = await this.getBusinessProfile(data.clientId);
    if (existing) {
      const [updated] = await db.update(businessProfiles)
        .set({ ...data, updatedAt: new Date() })
        .where(eq(businessProfiles.clientId, data.clientId))
        .returning();
      return updated;
    }
    const [created] = await db.insert(businessProfiles).values(data).returning();
    return created;
  }

  async getProductCatalog(clientId: number): Promise<ProductCatalogItem[]> {
    return db.select().from(productCatalog).where(eq(productCatalog.clientId, clientId)).orderBy(desc(productCatalog.createdAt));
  }

  async createProductCatalogItem(item: InsertProductCatalog): Promise<ProductCatalogItem> {
    const [created] = await db.insert(productCatalog).values(item).returning();
    return created;
  }

  async updateProductCatalogItem(id: number, data: Partial<ProductCatalogItem>): Promise<ProductCatalogItem | undefined> {
    const [updated] = await db.update(productCatalog).set(data).where(eq(productCatalog.id, id)).returning();
    return updated;
  }

  async deleteProductCatalogItem(id: number): Promise<void> {
    await db.delete(productCatalog).where(eq(productCatalog.id, id));
  }
}

export const storage = new DatabaseStorage();
