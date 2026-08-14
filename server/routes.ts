import type { Express, Request, RequestHandler } from "express";
import { createServer, type Server } from "http";
import { storage } from "./storage";
import { z } from "zod";
import OpenAI from "openai";
import crypto from "crypto";
import { setupAuth, registerAuthRoutes, isAuthenticated } from "./replit_integrations/auth";
import { speechToText, convertWebmToWav, textToSpeech } from "./replit_integrations/audio/client";
import { BigQueryService, type QueryResult } from "./services/bigquery";
import multer from "multer";
import path from "path";
import fs from "fs";
import { ObjectStorageService, registerObjectStorageRoutes } from "./replit_integrations/object_storage";
import { sendTeamInviteEmail } from "./services/email";

const objectStorageService = new ObjectStorageService();

const avatarMemoryUpload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 5 * 1024 * 1024 },
  fileFilter: (_req, file, cb) => {
    const allowed = ["image/jpeg", "image/png", "image/gif", "image/webp"];
    if (allowed.includes(file.mimetype)) {
      cb(null, true);
    } else {
      cb(new Error("Invalid file type. Only JPEG, PNG, GIF, and WebP are allowed."));
    }
  },
});

const openai = new OpenAI({
  apiKey: process.env.AI_INTEGRATIONS_OPENAI_API_KEY,
  baseURL: process.env.AI_INTEGRATIONS_OPENAI_BASE_URL,
});

class AIServiceError extends Error {
  constructor(message: string, public readonly cause?: any) {
    super(message);
    this.name = "AIServiceError";
  }
}

async function callOpenAIWithTimeoutAndRetry(
  params: Parameters<typeof openai.chat.completions.create>[0],
  options?: { timeoutMs?: number; maxRetries?: number }
): Promise<any> {
  const timeoutMs = options?.timeoutMs ?? 25000;
  const maxRetries = options?.maxRetries ?? 1;

  let lastError: any = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await openai.chat.completions.create(params, {
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      return response;
    } catch (err: any) {
      clearTimeout(timeoutId);
      lastError = err;

      const status: number | undefined = err?.status;
      const isAbort = err?.name === "AbortError" || controller.signal.aborted;
      const isTransient = isAbort || (typeof status === "number" && status >= 500);

      if (!isTransient || attempt >= maxRetries) {
        break;
      }

      const backoffMs = 1500 * (attempt + 1);
      console.warn(
        `[AI] Transient failure (attempt ${attempt + 1}/${maxRetries + 1}), retrying in ${backoffMs}ms — ${isAbort ? "timeout" : `status ${status}`}`
      );
      await new Promise((r) => setTimeout(r, backoffMs));
    }
  }

  const status: number | undefined = lastError?.status;
  const isAbort =
    lastError?.name === "AbortError" ||
    (typeof lastError?.message === "string" && lastError.message.toLowerCase().includes("abort"));

  if (isAbort) {
    throw new AIServiceError("AI service timed out", lastError);
  }
  if (typeof status === "number" && status >= 500) {
    throw new AIServiceError(`AI service returned ${status}`, lastError);
  }
  throw lastError;
}

// Helper: retry BigQuery execution once on transient network/service errors
const BQ_TRANSIENT_PATTERNS = [/socket hang up/i, /ECONNRESET/i, /ETIMEDOUT/i, /503/i, /service unavailable/i, /timeout/i, /temporarily unavailable/i];
async function executeQueryWithRetry(
  bqService: BigQueryService,
  sql: string,
  options: { maxRows?: number; timeoutMs?: number }
): Promise<QueryResult> {
  for (let attempt = 0; attempt <= 1; attempt++) {
    try {
      return await bqService.executeQuery(sql, options);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      const isTransient = BQ_TRANSIENT_PATTERNS.some(p => p.test(msg));
      if (!isTransient || attempt >= 1) throw err;
      console.warn(`[BQ] Transient error on attempt ${attempt + 1}, retrying in 1s: ${msg}`);
      await new Promise(r => setTimeout(r, 1000));
    }
  }
  throw new Error("executeQueryWithRetry exhausted attempts");
}

// Helper to get user ID from authenticated request (supports both OIDC and token sessions)
function getUserId(req: Request): string {
  const tokenSession = (req.session as any)?.tokenAuth;
  if (tokenSession) {
    return tokenSession.adminUserId;
  }
  return (req.user as any)?.claims?.sub;
}

// Helper to get team member ID from token session
function getTokenTeamMemberId(req: Request): number | null {
  return (req.session as any)?.tokenAuth?.teamMemberId || null;
}

// Middleware that accepts both OIDC auth and token-based sessions
const isAuthenticatedOrToken: RequestHandler = (req, res, next) => {
  const tokenSession = (req.session as any)?.tokenAuth;
  if (tokenSession?.adminUserId && tokenSession?.teamMemberId) {
    return next();
  }
  return (isAuthenticated as RequestHandler)(req, res, next);
};

// Helper to check if user is admin (not a viewer/collaborator)
async function isAdminUser(req: Request): Promise<boolean> {
  if ((req.session as any)?.tokenAuth) return false;
  const userId = getUserId(req);
  const membership = await storage.getTeamMembershipByUserId(userId);
  return !membership;
}

async function userCanAccessClient(userId: string, clientId: number): Promise<boolean> {
  const client = await storage.getClient(clientId);
  if (!client) return false;
  if (client.userId === userId) return true;
  const membership = await storage.getTeamMembershipByUserId(userId);
  if (!membership) return false;
  if (client.userId !== membership.adminUserId) return false;
  const assignedClients = await storage.getTeamMemberClients(membership.id);
  return assignedClients.some(ac => ac.clientId === clientId);
}

// For token sessions, check access via team member's assigned clients
async function tokenUserCanAccessClient(req: Request, clientId: number): Promise<boolean> {
  const tokenSession = (req.session as any)?.tokenAuth;
  if (!tokenSession) return false;
  const assignedClients = await storage.getTeamMemberClients(tokenSession.teamMemberId);
  return assignedClients.some(ac => ac.clientId === clientId);
}

// Combined access check - works for both OIDC and token sessions
async function canAccessClient(req: Request, clientId: number): Promise<boolean> {
  const tokenSession = (req.session as any)?.tokenAuth;
  if (tokenSession) {
    return tokenUserCanAccessClient(req, clientId);
  }
  return userCanAccessClient(getUserId(req), clientId);
}

export async function registerRoutes(
  httpServer: Server,
  app: Express
): Promise<Server> {
  
  // Setup authentication first
  await setupAuth(app);
  registerAuthRoutes(app);

  // Register object storage routes
  registerObjectStorageRoutes(app);

  // Token session auth check
  app.get("/api/auth/token-session", async (req, res) => {
    const tokenSession = (req.session as any)?.tokenAuth;
    if (!tokenSession) return res.json({ authenticated: false });
    const member = await storage.getTeamMember(tokenSession.teamMemberId);
    if (!member) {
      delete (req.session as any).tokenAuth;
      return res.json({ authenticated: false });
    }
    const assignedClients = await storage.getTeamMemberClients(member.id);
    res.json({
      authenticated: true,
      email: member.email,
      role: member.role,
      teamMemberId: member.id,
      adminUserId: member.adminUserId,
      assignedClientIds: assignedClients.map(ac => ac.clientId),
    });
  });

  // Token session logout (must be before :token catch-all)
  app.get("/api/shared/logout", async (req, res) => {
    delete (req.session as any).tokenAuth;
    req.session.save(() => res.redirect("/"));
  });

  // Shared token access - creates a session for collaborators without Replit Auth
  app.get("/api/shared/:token", async (req, res) => {
    try {
      const token = req.params.token;
      const member = await storage.getTeamMemberByShareToken(token);
      if (!member) return res.status(404).json({ error: "Invalid or expired link" });

      (req.session as any).tokenAuth = {
        adminUserId: member.adminUserId,
        teamMemberId: member.id,
        email: member.email,
        role: member.role,
      };

      if (member.status === "pending") {
        await storage.updateTeamMember(member.id, { status: "active" });
      }

      req.session.save((err) => {
        if (err) {
          console.error("Session save error:", err);
          return res.status(500).json({ error: "Failed to create session" });
        }
        res.redirect("/");
      });
    } catch (error) {
      console.error("Error processing shared token:", error);
      res.status(500).json({ error: "Failed to process shared link" });
    }
  });

  // Profile endpoints
  app.get("/api/profile", isAuthenticatedOrToken, async (req, res) => {
    try {
      const tokenSession = (req.session as any)?.tokenAuth;
      if (tokenSession) {
        return res.json({
          id: `token-${tokenSession.teamMemberId}`,
          email: tokenSession.email,
          firstName: tokenSession.email.split("@")[0],
          lastName: "",
          company: "",
          profileImageUrl: null,
        });
      }
      const userId = getUserId(req);
      const user = await storage.getUser(userId);
      if (!user) return res.status(404).json({ error: "User not found" });
      res.json({
        id: user.id,
        email: user.email,
        firstName: user.firstName,
        lastName: user.lastName,
        company: user.company,
        profileImageUrl: user.profileImageUrl,
      });
    } catch (error) {
      console.error("Error fetching profile:", error);
      res.status(500).json({ error: "Failed to fetch profile" });
    }
  });

  app.patch("/api/profile", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const profileSchema = z.object({
        firstName: z.string().optional(),
        lastName: z.string().optional(),
        email: z.string().email().optional(),
        company: z.string().optional(),
      });
      const parsed = profileSchema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ error: "Invalid profile data", details: parsed.error.flatten() });
      const { firstName, lastName, email, company } = parsed.data;
      const updateData: Record<string, any> = { updatedAt: new Date() };
      if (firstName !== undefined) updateData.firstName = firstName;
      if (lastName !== undefined) updateData.lastName = lastName;
      if (email !== undefined) updateData.email = email;
      if (company !== undefined) updateData.company = company;
      const updated = await storage.updateUser(userId, updateData);
      if (!updated) return res.status(404).json({ error: "User not found" });
      res.json({
        id: updated.id,
        email: updated.email,
        firstName: updated.firstName,
        lastName: updated.lastName,
        company: updated.company,
        profileImageUrl: updated.profileImageUrl,
      });
    } catch (error) {
      console.error("Error updating profile:", error);
      res.status(500).json({ error: "Failed to update profile" });
    }
  });

  app.post("/api/profile/avatar", isAuthenticated, (req, res, next) => {
    avatarMemoryUpload.single("avatar")(req, res, (err) => {
      if (err instanceof multer.MulterError) {
        return res.status(400).json({ error: err.code === "LIMIT_FILE_SIZE" ? "File too large. Maximum size is 5MB." : err.message });
      }
      if (err) return res.status(400).json({ error: err.message });
      next();
    });
  }, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!req.file) return res.status(400).json({ error: "No file uploaded" });

      const uploadURL = await objectStorageService.getObjectEntityUploadURL();
      const objectPath = objectStorageService.normalizeObjectEntityPath(uploadURL);

      const uploadResponse = await fetch(uploadURL, {
        method: "PUT",
        body: req.file.buffer,
        headers: {
          "Content-Type": req.file.mimetype,
        },
      });

      if (!uploadResponse.ok) {
        throw new Error(`Failed to upload to object storage: ${uploadResponse.status}`);
      }

      await storage.updateUser(userId, { profileImageUrl: objectPath });
      res.json({ profileImageUrl: objectPath });
    } catch (error) {
      console.error("Error uploading avatar:", error);
      res.status(500).json({ error: "Failed to upload avatar" });
    }
  });
  
  // ============================================================
  // Team Members / Collaborators
  // ============================================================

  app.get("/api/auth/role", isAuthenticatedOrToken, async (req, res) => {
    try {
      const tokenSession = (req.session as any)?.tokenAuth;
      if (tokenSession) {
        const assignedClients = await storage.getTeamMemberClients(tokenSession.teamMemberId);
        return res.json({
          role: tokenSession.role || "viewer",
          adminUserId: tokenSession.adminUserId,
          teamMemberId: tokenSession.teamMemberId,
          allowedClientIds: assignedClients.map((ac: any) => ac.clientId),
          isTokenSession: true,
        });
      }

      const userId = getUserId(req);
      const user = await storage.getUser(userId);
      if (!user) return res.status(404).json({ error: "User not found" });

      const membership = await storage.getTeamMembershipByUserId(userId);
      if (membership) {
        const assignedClients = await storage.getTeamMemberClients(membership.id);
        return res.json({
          role: "viewer",
          adminUserId: membership.adminUserId,
          teamMemberId: membership.id,
          allowedClientIds: assignedClients.map(ac => ac.clientId),
        });
      }

      return res.json({ role: "admin" });
    } catch (error) {
      console.error("Error fetching role:", error);
      res.status(500).json({ error: "Failed to fetch role" });
    }
  });

  app.get("/api/team", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const members = await storage.getTeamMembers(userId);
      const membersWithClients = await Promise.all(
        members.map(async (m) => {
          if (!m.shareToken) {
            const token = crypto.randomBytes(32).toString("hex");
            await storage.updateTeamMember(m.id, { shareToken: token });
            m = { ...m, shareToken: token };
          }
          const assignedClients = await storage.getTeamMemberClients(m.id);
          return { ...m, assignedClientIds: assignedClients.map(ac => ac.clientId) };
        })
      );
      res.json(membersWithClients);
    } catch (error) {
      console.error("Error fetching team:", error);
      res.status(500).json({ error: "Failed to fetch team members" });
    }
  });

  app.post("/api/team", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const schema = z.object({
        email: z.string().email(),
        clientIds: z.array(z.number()).min(1, "At least one client is required"),
      });
      const parsed = schema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ error: "Invalid data", details: parsed.error.flatten() });

      const { email, clientIds } = parsed.data;

      const existing = await storage.getTeamMemberByEmail(userId, email);
      if (existing) return res.status(409).json({ error: "This email is already on your team" });

      const invitedUser = await storage.getUserByEmail(email.toLowerCase());

      const shareToken = crypto.randomBytes(32).toString("hex");

      const member = await storage.createTeamMember({
        adminUserId: userId,
        email: email.toLowerCase(),
        role: "viewer",
        status: invitedUser ? "active" : "pending",
        userId: invitedUser?.id || null,
        shareToken,
      });

      await storage.setTeamMemberClients(member.id, clientIds);
      const assignedClients = await storage.getTeamMemberClients(member.id);

      const adminUser = await storage.getUser(userId);
      const allClients = await storage.getClients(userId);
      const clientNames = allClients
        .filter(c => clientIds.includes(c.id))
        .map(c => c.name);

      sendTeamInviteEmail({
        toEmail: email,
        inviterName: adminUser?.firstName
          ? `${adminUser.firstName} ${adminUser.lastName || ""}`.trim()
          : "Tu administrador",
        clientNames,
        shareToken,
      }).catch(err => console.error("Email send error (non-blocking):", err));

      res.json({ ...member, assignedClientIds: assignedClients.map(ac => ac.clientId) });
    } catch (error) {
      console.error("Error inviting team member:", error);
      res.status(500).json({ error: "Failed to invite team member" });
    }
  });

  app.patch("/api/team/:id", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const memberId = parseInt(req.params.id as string);
      const member = await storage.getTeamMember(memberId);
      if (!member || member.adminUserId !== userId) return res.status(404).json({ error: "Team member not found" });

      const schema = z.object({
        clientIds: z.array(z.number()).min(1).optional(),
      });
      const parsed = schema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ error: "Invalid data" });

      if (parsed.data.clientIds) {
        await storage.setTeamMemberClients(memberId, parsed.data.clientIds);
      }

      const assignedClients = await storage.getTeamMemberClients(memberId);
      res.json({ ...member, assignedClientIds: assignedClients.map(ac => ac.clientId) });
    } catch (error) {
      console.error("Error updating team member:", error);
      res.status(500).json({ error: "Failed to update team member" });
    }
  });

  app.delete("/api/team/:id", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const memberId = parseInt(req.params.id as string);
      const member = await storage.getTeamMember(memberId);
      if (!member || member.adminUserId !== userId) return res.status(404).json({ error: "Team member not found" });
      await storage.deleteTeamMember(memberId);
      res.json({ success: true });
    } catch (error) {
      console.error("Error removing team member:", error);
      res.status(500).json({ error: "Failed to remove team member" });
    }
  });

  // ============================================================
  // Clients (with collaborator access control)
  // ============================================================

  app.get("/api/clients", isAuthenticatedOrToken, async (req, res) => {
    try {
      const tokenSession = (req.session as any)?.tokenAuth;
      if (tokenSession) {
        const assignedClients = await storage.getTeamMemberClients(tokenSession.teamMemberId);
        const clientIds = assignedClients.map((ac: any) => ac.clientId);
        const adminClients = await storage.getClients(tokenSession.adminUserId);
        const filtered = adminClients.filter((c: any) => clientIds.includes(c.id));
        return res.json(filtered);
      }

      const userId = getUserId(req);
      const membership = await storage.getTeamMembershipByUserId(userId);
      if (membership) {
        const assignedClients = await storage.getTeamMemberClients(membership.id);
        const clientIds = assignedClients.map(ac => ac.clientId);
        const adminClients = await storage.getClients(membership.adminUserId);
        const filtered = adminClients.filter(c => clientIds.includes(c.id));
        return res.json(filtered);
      }

      const clients = await storage.getClients(userId);
      res.json(clients);
    } catch (error) {
      console.error("Error fetching clients:", error);
      res.status(500).json({ error: "Failed to fetch clients" });
    }
  });

  app.post("/api/clients", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const client = await storage.createClient({
        userId,
        ...req.body,
      });
      res.json(client);
    } catch (error) {
      console.error("Error creating client:", error);
      res.status(500).json({ error: "Failed to create client" });
    }
  });

  app.patch("/api/clients/:id", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const clientId = parseInt(req.params.id as string);
      
      // Verify client belongs to user
      const existingClient = await storage.getClient(clientId);
      if (!existingClient || existingClient.userId !== userId) {
        return res.status(404).json({ error: "Client not found" });
      }
      
      // Whitelist only allowed fields for update
      const allowedFields: Partial<{ connectionId: number | null; name: string; industry: string; primaryColor: string; logoUrl: string | null }> = {};
      if (req.body.connectionId !== undefined) allowedFields.connectionId = req.body.connectionId;
      if (req.body.name !== undefined) allowedFields.name = req.body.name;
      if (req.body.industry !== undefined) allowedFields.industry = req.body.industry;
      if (req.body.primaryColor !== undefined) allowedFields.primaryColor = req.body.primaryColor;
      if (req.body.logoUrl !== undefined) allowedFields.logoUrl = req.body.logoUrl;
      
      const updated = await storage.updateClient(clientId, allowedFields);
      res.json(updated);
    } catch (error) {
      console.error("Error updating client:", error);
      res.status(500).json({ error: "Failed to update client" });
    }
  });

  // ============================================================
  // Business Profiles & Product Catalog
  // ============================================================

  app.get("/api/business-profile/:clientId", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const clientId = parseInt(req.params.clientId as string);
      if (!await canAccessClient(req, clientId)) return res.status(403).json({ error: "Access denied" });
      const profile = await storage.getBusinessProfile(clientId);
      res.json(profile || null);
    } catch (error) {
      console.error("Error fetching business profile:", error);
      res.status(500).json({ error: "Failed to fetch business profile" });
    }
  });

  app.put("/api/business-profile/:clientId", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const clientId = parseInt(req.params.clientId as string);
      if (!await canAccessClient(req, clientId)) return res.status(403).json({ error: "Access denied" });
      const schema = z.object({
        description: z.string().optional().nullable(),
        targetAudience: z.string().optional().nullable(),
        additionalInfo: z.string().optional().nullable(),
      });
      const parsed = schema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ error: "Invalid data" });
      const profile = await storage.upsertBusinessProfile({ clientId, ...parsed.data });
      res.json(profile);
    } catch (error) {
      console.error("Error saving business profile:", error);
      res.status(500).json({ error: "Failed to save business profile" });
    }
  });

  app.get("/api/product-catalog/:clientId", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const clientId = parseInt(req.params.clientId as string);
      if (!await canAccessClient(req, clientId)) return res.status(403).json({ error: "Access denied" });
      const items = await storage.getProductCatalog(clientId);
      res.json(items);
    } catch (error) {
      console.error("Error fetching product catalog:", error);
      res.status(500).json({ error: "Failed to fetch product catalog" });
    }
  });

  app.post("/api/product-catalog/:clientId", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const clientId = parseInt(req.params.clientId as string);
      if (!await canAccessClient(req, clientId)) return res.status(403).json({ error: "Access denied" });
      const schema = z.object({
        name: z.string().min(1),
        description: z.string().optional().nullable(),
        benefits: z.string().optional().nullable(),
        cost: z.string().optional().nullable(),
        price: z.string().optional().nullable(),
        category: z.string().optional().nullable(),
      });
      const parsed = schema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ error: "Invalid data", details: parsed.error.flatten() });
      const item = await storage.createProductCatalogItem({ clientId, ...parsed.data });
      res.json(item);
    } catch (error) {
      console.error("Error creating product:", error);
      res.status(500).json({ error: "Failed to create product" });
    }
  });

  app.patch("/api/product-catalog/:clientId/:id", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const clientId = parseInt(req.params.clientId as string);
      if (!await canAccessClient(req, clientId)) return res.status(403).json({ error: "Access denied" });
      const id = parseInt(req.params.id as string);
      const existingItems = await storage.getProductCatalog(clientId);
      if (!existingItems.some(item => item.id === id)) return res.status(404).json({ error: "Product not found" });
      const schema = z.object({
        name: z.string().min(1).optional(),
        description: z.string().optional().nullable(),
        benefits: z.string().optional().nullable(),
        cost: z.string().optional().nullable(),
        price: z.string().optional().nullable(),
        category: z.string().optional().nullable(),
      });
      const parsed = schema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ error: "Invalid data" });
      const updated = await storage.updateProductCatalogItem(id, parsed.data);
      res.json(updated);
    } catch (error) {
      console.error("Error updating product:", error);
      res.status(500).json({ error: "Failed to update product" });
    }
  });

  app.delete("/api/product-catalog/:clientId/:id", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const clientId = parseInt(req.params.clientId as string);
      if (!await canAccessClient(req, clientId)) return res.status(403).json({ error: "Access denied" });
      const id = parseInt(req.params.id as string);
      const existingItems = await storage.getProductCatalog(clientId);
      if (!existingItems.some(item => item.id === id)) return res.status(404).json({ error: "Product not found" });
      await storage.deleteProductCatalogItem(id);
      res.json({ success: true });
    } catch (error) {
      console.error("Error deleting product:", error);
      res.status(500).json({ error: "Failed to delete product" });
    }
  });

  app.get("/api/connections", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const connections = await storage.getConnections(userId);
      res.json(connections.map(c => ({ ...c, credentials: "[ENCRYPTED]" })));
    } catch (error) {
      console.error("Error fetching connections:", error);
      res.status(500).json({ error: "Failed to fetch connections" });
    }
  });

  app.post("/api/connections", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const { name, projectId, datasetId, credentials } = req.body;
      const connection = await storage.createConnection({
        userId,
        name,
        projectId,
        datasetId,
        credentials,
        isActive: true,
      });
      res.json({ ...connection, credentials: "[ENCRYPTED]" });
    } catch (error) {
      console.error("Error creating connection:", error);
      res.status(500).json({ error: "Failed to create connection" });
    }
  });

  app.post("/api/connections/:id/test", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      
      // Get connection with credentials
      const connection = await storage.getConnection(id);
      if (!connection) {
        return res.status(404).json({ error: "Connection not found" });
      }
      if (connection.userId !== userId) {
        return res.status(403).json({ error: "Access denied" });
      }

      // Test BigQuery connection
      const bqService = BigQueryService.fromCredentialsJson(
        connection.projectId,
        connection.credentials,
        connection.datasetId || undefined
      );
      
      const result = await bqService.testConnection();
      
      // Update connection status
      const updated = await storage.updateConnection(id, {
        lastTestedAt: new Date(),
        isActive: result.success,
      });

      // If successful, discover schema
      let schemaCount = 0;
      if (result.success) {
        let schemas: any[] = [];
        
        // Try API-based discovery first (undefined = discover ALL datasets)
        try {
          schemas = await bqService.discoverSchema(undefined);
        } catch (apiError: any) {
          console.log("API schema discovery failed, trying SQL-based discovery:", apiError.message);
        }
        
        // If API fails, try SQL-based discovery across all datasets
        if (schemas.length === 0) {
          try {
            schemas = await bqService.discoverSchemaViaSql(undefined);
            console.log(`SQL discovery found ${schemas.length} columns`);
          } catch (sqlError: any) {
            console.log("SQL schema discovery also failed:", sqlError.message);
          }
        }
        
        if (schemas.length > 0) {
          // Clear existing schemas for this connection
          await storage.deleteConnectionSchemas(id);
          // Store new schemas
          for (const schema of schemas) {
            await storage.createConnectionSchema({
              connectionId: id,
              ...schema,
            });
          }
          schemaCount = schemas.length;
        }
      }

      res.json({ 
        success: result.success, 
        message: result.message + (schemaCount > 0 ? ` Discovered ${schemaCount} columns.` : ""),
        schemaCount,
        connection: { ...updated, credentials: "[ENCRYPTED]" } 
      });
    } catch (error: any) {
      console.error("Error testing connection:", error);
      res.status(500).json({ error: error.message || "Connection test failed" });
    }
  });

  // Get connection schema
  app.get("/api/connections/:id/schema", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      
      const connection = await storage.getConnection(id);
      if (!connection) {
        return res.status(404).json({ error: "Connection not found" });
      }
      if (connection.userId !== userId) {
        return res.status(403).json({ error: "Access denied" });
      }

      const schemas = await storage.getConnectionSchemas(id);
      res.json(schemas);
    } catch (error) {
      console.error("Error fetching schema:", error);
      res.status(500).json({ error: "Failed to fetch schema" });
    }
  });

  // Refresh connection schema
  app.post("/api/connections/:id/refresh-schema", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      
      const connection = await storage.getConnection(id);
      if (!connection) {
        return res.status(404).json({ error: "Connection not found" });
      }
      if (connection.userId !== userId) {
        return res.status(403).json({ error: "Access denied" });
      }

      const bqService = BigQueryService.fromCredentialsJson(
        connection.projectId,
        connection.credentials,
        connection.datasetId || undefined
      );

      let schemas: any[] = [];
      
      // Try API-based discovery first (undefined = discover ALL datasets)
      try {
        schemas = await bqService.discoverSchema(undefined);
      } catch (apiError: any) {
        console.log("API schema discovery failed, trying SQL-based discovery:", apiError.message);
      }
      
      // If API fails, try SQL-based discovery across all datasets
      if (schemas.length === 0) {
        try {
          schemas = await bqService.discoverSchemaViaSql(undefined);
          console.log(`SQL discovery found ${schemas.length} columns`);
        } catch (sqlError: any) {
          console.log("SQL schema discovery also failed:", sqlError.message);
          throw new Error(`Schema discovery failed: ${sqlError.message}`);
        }
      }
      
      // Clear existing schemas
      await storage.deleteConnectionSchemas(id);
      
      // Store new schemas
      for (const schema of schemas) {
        await storage.createConnectionSchema({
          connectionId: id,
          ...schema,
        });
      }

      res.json({ success: true, count: schemas.length });
    } catch (error: any) {
      console.error("Error refreshing schema:", error);
      res.status(500).json({ error: error.message || "Failed to refresh schema" });
    }
  });

  app.delete("/api/connections/:id", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const id = parseInt(req.params.id as string);
      await storage.deleteConnection(id);
      res.json({ success: true });
    } catch (error) {
      console.error("Error deleting connection:", error);
      res.status(500).json({ error: "Failed to delete connection" });
    }
  });

  app.get("/api/segments", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const clientId = req.query.clientId ? parseInt(req.query.clientId as string) : undefined;
      const segments = await storage.getSegments(userId, clientId);
      res.json(segments);
    } catch (error) {
      console.error("Error fetching segments:", error);
      res.status(500).json({ error: "Failed to fetch segments" });
    }
  });

  app.post("/api/segments", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const segment = await storage.createSegment({
        userId,
        name: req.body.name,
        description: req.body.description,
        clientId: req.body.clientId,
        criteria: req.body.criteria || {},
        isAiGenerated: false,
        status: "active",
        contactCount: 0,
      });
      res.json(segment);
    } catch (error) {
      console.error("Error creating segment:", error);
      res.status(500).json({ error: "Failed to create segment" });
    }
  });

  // Create segment from query results
  app.post("/api/segments/from-query", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const { name, description, sql, memberData, contactCount, clientId } = req.body;

      // Validate required fields
      if (!name || typeof name !== 'string' || name.trim().length === 0) {
        return res.status(400).json({ error: "Segment name is required" });
      }

      if (name.length > 100) {
        return res.status(400).json({ error: "Segment name too long (max 100 characters)" });
      }

      // Validate memberData if provided
      if (memberData !== undefined && memberData !== null) {
        if (!Array.isArray(memberData)) {
          return res.status(400).json({ error: "memberData must be an array" });
        }
        if (memberData.length > 10000) {
          return res.status(400).json({ error: "Maximum 10,000 members allowed per segment" });
        }
      }

      // Validate clientId access if provided
      if (clientId) {
        const hasAccess = await canAccessClient(req, clientId);
        if (!hasAccess) {
          return res.status(403).json({ error: "Invalid client ID" });
        }
      }

      console.log("[SEGMENT-FROM-QUERY] Creating segment from query");
      console.log("[SEGMENT-FROM-QUERY] Name:", name);
      console.log("[SEGMENT-FROM-QUERY] Members:", memberData?.length || 0);

      // Create the segment
      const segment = await storage.createSegment({
        userId,
        name: name.trim(),
        description: description || `Segmento creado desde consulta`,
        clientId: clientId || null,
        criteria: { 
          source: "query",
          createdFrom: "natural_language_query",
        },
        isAiGenerated: false,
        status: "active",
        contactCount: contactCount || memberData?.length || 0,
      });

      // Update with member data and SQL
      const updatedSegment = await storage.updateSegment(segment.id, {
        generatedSql: sql || null,
        memberData: memberData || null,
      });

      console.log("[SEGMENT-FROM-QUERY] Segment created successfully:", segment.id);
      res.json(updatedSegment);
    } catch (error) {
      console.error("[SEGMENT-FROM-QUERY] Error:", error);
      res.status(500).json({ error: "Failed to create segment from query" });
    }
  });

  app.post("/api/segments/generate", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const clientId = req.body.clientId ? parseInt(req.body.clientId) : null;
      
      console.log("[SEGMENT-GEN] Starting segment generation");
      console.log("[SEGMENT-GEN] userId:", userId);
      console.log("[SEGMENT-GEN] clientId from request:", clientId);
      
      // Get client and its BigQuery connection
      let connection = null;
      let projectId = "";
      let datasetId = "";
      
      if (clientId) {
        const client = await storage.getClient(clientId);
        console.log("[SEGMENT-GEN] Client found:", client?.id, client?.name, "connectionId:", client?.connectionId);
        if (client?.connectionId) {
          connection = await storage.getConnection(client.connectionId);
          console.log("[SEGMENT-GEN] Got connection from client:", connection?.id, connection?.name);
        }
      }
      
      // If no client or no connection, try to get any connection for this user
      if (!connection) {
        console.log("[SEGMENT-GEN] No connection from client, trying user connections...");
        const connections = await storage.getConnections(userId);
        console.log("[SEGMENT-GEN] User connections found:", connections.length);
        connections.forEach((c, i) => console.log(`[SEGMENT-GEN]   [${i}] id:${c.id} name:${c.name} project:${c.projectId}`));
        if (connections.length > 0) {
          connection = connections[0];
          console.log("[SEGMENT-GEN] Using first user connection:", connection.id, connection.name);
        }
      }
      
      if (!connection) {
        console.log("[SEGMENT-GEN] ERROR: No connection found for user");
        return res.status(400).json({ 
          error: "No BigQuery connection available. Please configure a BigQuery connection first." 
        });
      }
      
      projectId = connection.projectId;
      datasetId = connection.datasetId || "";
      console.log("[SEGMENT-GEN] Using BigQuery - project:", projectId, "dataset:", datasetId);
      
      // Initialize BigQuery service
      console.log("[SEGMENT-GEN] Initializing BigQuery service...");
      const bqService = BigQueryService.fromCredentialsJson(
        projectId,
        connection.credentials,
        datasetId
      );
      
      // Discover schema to understand the data (all datasets in the project)
      console.log("[SEGMENT-GEN] Discovering schema...");
      const schemas = await bqService.discoverSchemaViaSql(undefined);
      const uniqueTables = [...new Set(schemas.map(s => s.tableName))];
      console.log("[SEGMENT-GEN] Schema discovered - columns:", schemas.length, "tables:", uniqueTables.length);
      uniqueTables.forEach(t => console.log(`[SEGMENT-GEN]   Table: ${t}`));
      const schemaPrompt = bqService.formatSchemaForPrompt(schemas, projectId);
      
      // Get existing segments to avoid duplicates
      const existingSegments = await storage.getSegments(userId, clientId || undefined);
      const existingSegmentNames = existingSegments.map(s => s.name);
      const existingSegmentTypes = existingSegments
        .filter(s => s.isAiGenerated)
        .map(s => (s.criteria as any)?.segmentType || 'unknown');
      console.log("[SEGMENT-GEN] Existing segments:", existingSegmentNames.length);
      console.log("[SEGMENT-GEN] Existing AI segment types:", existingSegmentTypes.join(", "));
      
      // Get a sample of customer data to understand patterns
      const customersTable = schemas.find(s => 
        s.tableName.toLowerCase().includes('customer') || 
        s.tableName.toLowerCase().includes('users')
      );
      const subscriptionsTable = schemas.find(s => 
        s.tableName.toLowerCase().includes('subscription') || 
        s.tableName.toLowerCase().includes('order') ||
        s.tableName.toLowerCase().includes('purchase')
      );
      
      // Use OpenAI to analyze and recommend a segment
      console.log("[SEGMENT-GEN] Calling OpenAI for segment recommendation...");
      const aiResponse = await callOpenAIWithTimeoutAndRetry({
        model: "gpt-4o-mini",
        messages: [
          {
            role: "system",
            content: `Eres un experto en segmentación de clientes para retail y e-commerce. 
Tu tarea es analizar la estructura de datos de BigQuery y recomendar UN segmento de clientes valioso.

Debes responder SIEMPRE en formato JSON con esta estructura exacta:
{
  "segmentName": "Nombre del segmento en español",
  "description": "Descripción detallada del segmento en español (2-3 oraciones)",
  "segmentType": "churn_risk|high_value|new_customers|frequent_buyers|inactive",
  "criteria": {
    "explanation": "Explicación de los criterios usados",
    "confidence": 0.85
  },
  "sql": "SELECT customer_id, email, ... FROM table WHERE conditions LIMIT 10000"
}

REGLAS CRÍTICAS para el SQL:
1. SIEMPRE usa referencias completas con backticks: \`project.dataset.table\`
2. SIEMPRE incluye customer_id o el campo identificador principal
3. SIEMPRE incluye email si existe en el schema
4. SIEMPRE incluye el nombre del cliente (name, first_name/last_name) y teléfono/phone si existen en el schema - estos campos son OBLIGATORIOS para la integración con CRM
5. SIEMPRE agrega LIMIT 10000 al final (permitimos hasta 10,000 resultados)
6. Solo SELECT, nunca modificaciones
7. El SQL debe ser ejecutable directamente en BigQuery
8. USA SOLO los campos que aparecen en el schema proporcionado - NO inventes campos como 'balance', 'saldo', 'total_spent' si no existen
9. Si necesitas calcular totales, usa SUM() sobre campos numéricos existentes como 'amount'
10. Para suscripciones activas, usa status = 'active'
11. Para fechas, usa campos existentes como 'created' o 'current_period_end'
12. MAPEO DE PRODUCTOS/TIERS - Cuando el usuario mencione un tier o producto por nombre, usa el product_id correspondiente:
  - "Basic Wash" = product_id 'prod_LQjx67EvzQ1PGQ'
  - "Premium Wash" = product_id 'prod_LQjy3uY1m2leN3'
  - "BW/Road Assistance" (mensual) = product_id 'prod_QokBj7SE3bnVgn'
  - "BW/Road Assistance Yearly" = product_id 'prod_TEj2sqBLZUBBby'
  Siempre filtra por product_id (no por nombre) cuando el usuario pregunte por un tier/plan específico.`
          },
          {
            role: "user",
            content: `Analiza esta estructura de datos y recomienda un segmento valioso de clientes:

${schemaPrompt}

${existingSegmentNames.length > 0 ? `
IMPORTANTE: Ya existen estos segmentos, NO los repitas ni uses nombres similares:
${existingSegmentNames.map(n => `- "${n}"`).join('\n')}

Debes generar un segmento DIFERENTE y ÚNICO que no exista en la lista anterior.
` : ''}

Basándote en las tablas disponibles, identifica un segmento de clientes que sería valioso para campañas de marketing. 
Genera el SQL para obtener los miembros del segmento.`
          }
        ],
        temperature: 0.3,
        max_tokens: 1500,
      }, { timeoutMs: 12000, maxRetries: 1 });
      
      const aiContent = aiResponse.choices[0]?.message?.content || "";
      console.log("[SEGMENT-GEN] OpenAI response received, length:", aiContent.length);
      console.log("[SEGMENT-GEN] AI Response preview:", aiContent.substring(0, 300) + "...");
      
      // Parse AI response
      let segmentData;
      try {
        // Extract JSON from response (handle markdown code blocks)
        const jsonMatch = aiContent.match(/\{[\s\S]*\}/);
        if (jsonMatch) {
          segmentData = JSON.parse(jsonMatch[0]);
          console.log("[SEGMENT-GEN] Parsed segment data - name:", segmentData.segmentName);
          console.log("[SEGMENT-GEN] Generated SQL:", segmentData.sql ? segmentData.sql.substring(0, 100) + "..." : "none");
        } else {
          throw new Error("No JSON found in AI response");
        }
      } catch (parseError) {
        console.error("[SEGMENT-GEN] Failed to parse AI response:", aiContent);
        throw new Error("La IA devolvió una respuesta que no pudo procesarse. Por favor intenta de nuevo.");
      }
      
      // Try to execute the generated SQL to get segment members
      let memberData: any[] = [];
      let contactCount = 0;
      let generatedSql = segmentData.sql || null;
      let sqlExecutionError: string | null = null;
      
      if (generatedSql) {
        console.log("[SEGMENT-GEN] Executing generated SQL to get segment members...");
        console.log("[SEGMENT-GEN] Full SQL:", generatedSql);
        try {
          const result = await bqService.executeQuery(generatedSql, { maxRows: 10000 });
          memberData = result.rows;
          contactCount = result.totalRows;
          console.log("[SEGMENT-GEN] SQL executed successfully - rows:", memberData.length, "total:", contactCount);
          
          // If no results, try a simpler fallback query
          if (memberData.length === 0) {
            console.log("[SEGMENT-GEN] No results found, trying fallback query...");
            const fallbackSql = `SELECT customer_id, email FROM \`${projectId}.${datasetId}.customers\` LIMIT 100`;
            try {
              const fallbackResult = await bqService.executeQuery(fallbackSql, { maxRows: 100 });
              if (fallbackResult.rows.length > 0) {
                memberData = fallbackResult.rows;
                contactCount = fallbackResult.totalRows;
                generatedSql = fallbackSql;
                console.log("[SEGMENT-GEN] Fallback query succeeded - rows:", memberData.length);
              }
            } catch (fallbackError) {
              console.log("[SEGMENT-GEN] Fallback query also failed");
            }
          }
        } catch (sqlError: any) {
          console.error("[SEGMENT-GEN] SQL execution error:", sqlError.message);
          console.error("[SEGMENT-GEN] Failed SQL:", generatedSql);
          sqlExecutionError = sqlError.message;
          
          // Try a simpler fallback query
          console.log("[SEGMENT-GEN] Trying fallback query due to error...");
          const fallbackSql = `SELECT customer_id, email FROM \`${projectId}.${datasetId}.customers\` LIMIT 100`;
          try {
            const fallbackResult = await bqService.executeQuery(fallbackSql, { maxRows: 100 });
            memberData = fallbackResult.rows;
            contactCount = fallbackResult.totalRows;
            generatedSql = fallbackSql;
            console.log("[SEGMENT-GEN] Fallback query succeeded - rows:", memberData.length);
          } catch (fallbackError: any) {
            console.error("[SEGMENT-GEN] Fallback query also failed:", fallbackError.message);
            generatedSql = null;
          }
        }
      } else {
        console.log("[SEGMENT-GEN] No SQL generated, segment will have no member data");
      }
      
      // Create the segment with real data
      console.log("[SEGMENT-GEN] Creating segment in database...");
      const segmentCriteria = {
        ...segmentData.criteria,
        aiGenerated: true,
        segmentType: segmentData.segmentType,
        ...(sqlExecutionError && { sqlError: sqlExecutionError }),
      };
      
      const segment = await storage.createSegment({
        userId,
        name: segmentData.segmentName || "Segmento AI",
        description: segmentData.description || "Segmento generado por inteligencia artificial.",
        clientId: clientId,
        criteria: segmentCriteria,
        isAiGenerated: true,
        status: "active",
        contactCount: contactCount || memberData.length,
      });
      console.log("[SEGMENT-GEN] Segment created with id:", segment.id);
      
      // Update segment with member data and SQL (using updateSegment to add extra fields)
      const updatedSegment = await storage.updateSegment(segment.id, {
        generatedSql,
        memberData: memberData.length > 0 ? memberData : null,
      });
      console.log("[SEGMENT-GEN] Segment updated with SQL and member data. Complete!");
      
      res.json(updatedSegment || segment);
    } catch (error: any) {
      console.error("[SEGMENT-GEN] ERROR:", error.message);
      console.error("[SEGMENT-GEN] Stack:", error.stack);
      if (res.headersSent) return;
      if (error instanceof AIServiceError) {
        res.status(503).json({ error: "El servicio de IA no está disponible temporalmente. Por favor intenta en un momento.", errorType: "ai_unavailable" });
      } else {
        res.status(500).json({ error: error.message || "Failed to generate segment", errorType: "unknown" });
      }
    }
  });

  // Get single segment with full details
  app.get("/api/segments/:id", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const segment = await storage.getSegment(id);
      
      if (!segment) {
        return res.status(404).json({ error: "Segment not found" });
      }
      
      // Ownership check - verify segment belongs to current user
      if (segment.userId !== userId) {
        return res.status(403).json({ error: "Access denied" });
      }
      
      res.json(segment);
    } catch (error) {
      console.error("Error fetching segment:", error);
      res.status(500).json({ error: "Failed to fetch segment" });
    }
  });

  // Get segment members (customer list)
  app.get("/api/segments/:id/members", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const segment = await storage.getSegment(id);
      
      if (!segment) {
        return res.status(404).json({ error: "Segment not found" });
      }
      
      // Ownership check - verify segment belongs to current user
      if (segment.userId !== userId) {
        return res.status(403).json({ error: "Access denied" });
      }
      
      // If we have cached member data, return it
      if (segment.memberData) {
        return res.json({
          members: segment.memberData,
          count: segment.contactCount || (segment.memberData as any[]).length,
          cached: true
        });
      }
      
      // If we have generated SQL, try to re-execute it for fresh data
      if (segment.generatedSql) {
        // Get the correct BigQuery connection based on segment's client
        let connection = null;
        
        if (segment.clientId) {
          const client = await storage.getClient(segment.clientId);
          if (client?.connectionId) {
            connection = await storage.getConnection(client.connectionId);
          }
        }
        
        // Fallback to user's first connection if no client-specific one
        if (!connection) {
          const connections = await storage.getConnections(userId);
          if (connections.length > 0) {
            connection = connections[0];
          }
        }
        
        if (connection) {
          try {
            const bqService = BigQueryService.fromCredentialsJson(
              connection.projectId,
              connection.credentials,
              connection.datasetId || ""
            );
            
            const result = await bqService.executeQuery(segment.generatedSql, { maxRows: 10000 });
            
            // Update cached member data
            await storage.updateSegment(id, {
              memberData: result.rows,
              contactCount: result.totalRows,
            });
            
            return res.json({
              members: result.rows,
              count: result.totalRows,
              cached: false
            });
          } catch (error: any) {
            console.error("Error re-executing segment SQL:", error.message);
          }
        }
      }
      
      // No member data available
      res.json({
        members: [],
        count: segment.contactCount || 0,
        cached: false,
        message: "No member data available for this segment"
      });
    } catch (error) {
      console.error("Error fetching segment members:", error);
      res.status(500).json({ error: "Failed to fetch segment members" });
    }
  });

  app.delete("/api/segments/:id", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      console.log("[SEGMENT-DELETE] Attempting to delete segment:", id, "by user:", userId);
      
      const segment = await storage.getSegment(id);
      
      if (!segment) {
        console.log("[SEGMENT-DELETE] Segment not found:", id);
        return res.status(404).json({ error: "Segment not found" });
      }
      
      console.log("[SEGMENT-DELETE] Found segment:", segment.id, segment.name, "owner:", segment.userId);
      
      // Ownership check - verify segment belongs to current user
      if (segment.userId !== userId) {
        console.log("[SEGMENT-DELETE] Access denied - segment owner:", segment.userId, "requester:", userId);
        return res.status(403).json({ error: "Access denied" });
      }
      
      await storage.deleteSegment(id);
      console.log("[SEGMENT-DELETE] Successfully deleted segment:", id);
      res.json({ success: true });
    } catch (error: any) {
      console.error("[SEGMENT-DELETE] Error deleting segment:", error.message, error.stack);
      res.status(500).json({ error: "Failed to delete segment" });
    }
  });

  app.get("/api/queries", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const limit = req.query.limit ? parseInt(req.query.limit as string) : 50;
      const queries = await storage.getQueries(userId, limit);
      res.json(queries);
    } catch (error) {
      console.error("Error fetching queries:", error);
      res.status(500).json({ error: "Failed to fetch queries" });
    }
  });

  app.get("/api/queries/saved", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const limit = req.query.limit ? parseInt(req.query.limit as string) : 10;
      const savedQueries = await storage.getSavedQueries(userId, limit);
      res.json(savedQueries);
    } catch (error) {
      console.error("Error fetching saved queries:", error);
      res.status(500).json({ error: "Failed to fetch saved queries" });
    }
  });

  app.patch("/api/queries/:id/save", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const queryId = parseInt(req.params.id as string);
      const { isSaved } = req.body;
      
      const query = await storage.getQuery(queryId);
      if (!query || query.userId !== userId) {
        return res.status(404).json({ error: "Query not found" });
      }
      
      const updated = await storage.updateQuery(queryId, { isSaved });
      res.json(updated);
    } catch (error) {
      console.error("Error updating query save status:", error);
      res.status(500).json({ error: "Failed to update query" });
    }
  });

  app.delete("/api/queries/:id", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const queryId = parseInt(req.params.id as string);
      
      const query = await storage.getQuery(queryId);
      if (!query || query.userId !== userId) {
        return res.status(404).json({ error: "Query not found" });
      }
      
      await storage.deleteQuery(queryId);
      res.json({ success: true });
    } catch (error) {
      console.error("Error deleting query:", error);
      res.status(500).json({ error: "Failed to delete query" });
    }
  });

  app.post("/api/queries", isAuthenticatedOrToken, async (req, res) => {
    const { naturalLanguage, clientId, connectionId, previousQueryContext, drillDownSql } = req.body;
    const recommendationPatterns = /\b(recomend|recomiend|sugier|suger|propon|propuesta|consejo|estrategia|plan de acci|que harias|que hago|que deberia|que puedo hacer|como puedo|como mejoro|como aumento|como reduzco|como optimizo|como incremento|aumentar|mejorar|reducir|optimizar|incrementar|disminuir|insights|recommend|suggest|advice|strategy|what should|what can i do|how can i|how do i|action plan|marketing plan|campaña|campaign|tips|acciones)\b/i;
    const isRecommendationIntent = recommendationPatterns.test(String(naturalLanguage || ""));
    try {
      const userId = getUserId(req);
      const startTime = Date.now();

      if (isRecommendationIntent && !previousQueryContext) {
        const lastQueries = await storage.getQueries(userId, 10);
        const lastWithData = lastQueries.find(q => q.resultData && Array.isArray(q.resultData) && (q.resultData as any[]).length > 0);
        if (lastWithData) {
          const prevData = (lastWithData.resultData as any[]).slice(0, 50);
          const reconstructedContext = {
            query: lastWithData.naturalLanguage,
            summary: lastWithData.resultSummary,
            data: prevData,
            totalRows: (lastWithData.resultData as any[]).length,
          };
          Object.assign(req.body, { previousQueryContext: reconstructedContext });
        }
      }

      const finalPreviousContext = req.body.previousQueryContext || previousQueryContext;
      const isRecommendationRequest = isRecommendationIntent;

      if (isRecommendationRequest) {
        const hasContext = finalPreviousContext && finalPreviousContext.data && finalPreviousContext.data.length > 0;
        const dataPreview = hasContext ? JSON.stringify(finalPreviousContext.data?.slice(0, 30), null, 2) : "No hay datos previos disponibles";
        const contextSection = hasContext 
          ? `DATOS PREVIOS DEL USUARIO:
- Pregunta original: "${finalPreviousContext.query}"
- Resumen: ${finalPreviousContext.summary}
- Total de registros: ${finalPreviousContext.totalRows || "N/A"}
- Muestra de datos:
${dataPreview}`
          : "No hay datos previos disponibles. Basa tus recomendaciones en mejores prácticas generales de la industria para el tema que el usuario pregunta.";

        let businessContextSection = "";
        if (clientId) {
          const businessProfile = await storage.getBusinessProfile(clientId);
          const catalogItems = await storage.getProductCatalog(clientId);

          if (businessProfile || catalogItems.length > 0) {
            businessContextSection = "\n\nCONTEXTO DEL NEGOCIO:";
            if (businessProfile) {
              if (businessProfile.description) businessContextSection += `\n- Descripción del negocio: ${businessProfile.description}`;
              if (businessProfile.targetAudience) businessContextSection += `\n- Público objetivo: ${businessProfile.targetAudience}`;
              if (businessProfile.additionalInfo) businessContextSection += `\n- Información adicional: ${businessProfile.additionalInfo}`;
            }
            if (catalogItems.length > 0) {
              businessContextSection += `\n\nCATÁLOGO DE PRODUCTOS (${catalogItems.length} productos):`;
              for (const item of catalogItems.slice(0, 30)) {
                businessContextSection += `\n- ${item.name}`;
                if (item.category) businessContextSection += ` [${item.category}]`;
                if (item.description) businessContextSection += `: ${item.description}`;
                if (item.benefits) businessContextSection += ` | Beneficios: ${item.benefits}`;
                if (item.cost) businessContextSection += ` | Costo: ${item.cost}`;
                if (item.price) businessContextSection += ` | Precio: ${item.price}`;
              }
            }
          }
        }

        const recommendationPrompt = `Eres un consultor experto en marketing y estrategia de negocios. El usuario te pide recomendaciones accionables.

${contextSection}${businessContextSection}

PREGUNTA ACTUAL DEL USUARIO: "${naturalLanguage}"

Responde en JSON con estos campos:
- recommendation: Un análisis detallado en español con recomendaciones de marketing accionables. Usa formato markdown con secciones claras (## para títulos, - para listas, **negrita** para destacar). Incluye: 1) Análisis de lo que muestran los datos, 2) Recomendaciones específicas y accionables basadas en el contexto del negocio y sus productos, 3) Métricas sugeridas para medir el éxito. Sé específico con los datos reales que ves. Si tienes información del catálogo de productos, menciona productos específicos en tus recomendaciones (ej: promociones, bundles, estrategias de precio).
- summary: Un resumen corto de una línea de las recomendaciones (string)`;

        const recResponse = await callOpenAIWithTimeoutAndRetry({
          model: "gpt-4o-mini",
          messages: [
            { role: "system", content: recommendationPrompt },
            { role: "user", content: naturalLanguage }
          ],
          response_format: { type: "json_object" },
          max_completion_tokens: 4096,
        }, { timeoutMs: 12000, maxRetries: 1 });

        const recContent = recResponse.choices[0]?.message?.content || "{}";
        let recParsed;
        try {
          recParsed = JSON.parse(recContent);
          if (!recParsed || typeof recParsed !== "object") throw new Error("Empty JSON");
        } catch {
          if (res.headersSent) return;
          return res.status(422).json({
            error: "No pude generar recomendaciones. Intenta reformular tu pregunta.",
            errorType: "parse_error",
          });
        }

        const executionTime = Date.now() - startTime;
        const query = await storage.createQuery({
          userId,
          clientId,
          naturalLanguage,
          generatedSql: null,
          resultSummary: recParsed.summary || "Recomendaciones de marketing",
          resultData: [],
          visualizationType: "table",
          executionTimeMs: executionTime,
          isSaved: false,
          isRecommendation: true,
          recommendationText: recParsed.recommendation,
        });

        return res.json({
          id: query.id,
          summary: recParsed.summary || "Recomendaciones de marketing",
          data: [],
          sql: null,
          executionTime,
          visualizationType: "table",
          isRecommendation: true,
          recommendation: recParsed.recommendation,
          usedRealData: false,
          isSaved: query.isSaved,
        });
      }

      let schemaContext = "";
      let bqService: BigQueryService | null = null;
      let connection: any = null;

      // If connectionId provided, get schema and prepare BigQuery service
      if (connectionId) {
        connection = await storage.getConnection(connectionId);
        if (connection && connection.userId === userId) {
          const tempService = BigQueryService.fromCredentialsJson(
            connection.projectId,
            connection.credentials,
            connection.datasetId || undefined
          );
          bqService = tempService;
          
          let schemas = await storage.getConnectionSchemas(connectionId);
          
          // If no schema discovered yet, try to discover it now via SQL (all datasets)
          if (schemas.length === 0) {
            console.log("No schema found, attempting SQL-based schema discovery across all datasets...");
            try {
              const discoveredSchemas = await tempService.discoverSchemaViaSql(undefined);
              if (discoveredSchemas.length > 0) {
                // Store the discovered schemas
                for (const schema of discoveredSchemas) {
                  await storage.createConnectionSchema({
                    connectionId,
                    ...schema,
                  });
                }
                schemas = await storage.getConnectionSchemas(connectionId);
                console.log(`Discovered and stored ${schemas.length} schema columns`);
              }
            } catch (schemaError: any) {
              console.log("SQL schema discovery failed:", schemaError.message);
              // Continue without schema - AI will do its best
            }
          }
          
          if (schemas.length > 0) {
            // Map database schema to BigQueryService's SchemaColumn format
            const schemaColumns = schemas.map(s => ({
              datasetName: s.datasetName,
              tableName: s.tableName,
              columnName: s.columnName,
              dataType: s.dataType,
              isNullable: s.isNullable ?? true,
              description: s.description ?? undefined,
            }));
            schemaContext = tempService.formatSchemaForPrompt(schemaColumns, connection.projectId);
          } else {
            // Even without schema, provide project context for SQL generation
            schemaContext = `Note: No table schema discovered yet. User's BigQuery project is "${connection.projectId}".
If the user mentions specific table names, use fully qualified format: \`${connection.projectId}.dataset_name.table_name\` with the correct dataset.`;
          }
        }
      }

      // Build project context for SQL generation
      const projectContext = connection ? 
        `Project ID: ${connection.projectId}
When referencing tables, use the fully qualified format: \`${connection.projectId}.dataset_name.table_name\`
The correct dataset name for each table is shown in the schema context above — use it exactly as listed there.` : "";

      let systemPrompt = schemaContext 
        ? `You are a data analytics AI assistant. The user will ask questions about their data.
Based on the schema provided, generate a valid BigQuery SQL query to answer their question.

${projectContext}

${schemaContext}

Respond in JSON format with these fields:
- sql: A valid BigQuery SQL query (string). You MUST use the exact project ID "${connection?.projectId}" in fully qualified table names like \`${connection?.projectId}.dataset_name.table_name\` format, using the correct dataset name for each table as shown in the schema context above.
- summary: What this query will return (string)
- visualizationType: One of "bar", "line", "pie", or "table" - choose based on the data type

PRODUCT/TIER MAPPING - When the user refers to tiers or products by name, use the corresponding product_id in your SQL:
- "Basic Wash" = product_id 'prod_LQjx67EvzQ1PGQ'
- "Premium Wash" = product_id 'prod_LQjy3uY1m2leN3'
- "BW/Road Assistance" (monthly) = product_id 'prod_QokBj7SE3bnVgn'
- "BW/Road Assistance Yearly" = product_id 'prod_TEj2sqBLZUBBby'
Always filter by product_id (not by name string) when the user asks about a specific tier/plan.

CHURN / CANCELLATION LOGIC - VERY IMPORTANT:
- Churn is determined by the \`canceled_at\` TIMESTAMP column, NOT by a status field. A subscription is considered "canceled" if \`canceled_at IS NOT NULL\`.
- To calculate churn rate: count rows where canceled_at IS NOT NULL (in a period) divided by total active subscriptions at the start of that period, times 100.
- "Active at start of period" means: subscriptions created (date column) BEFORE the period start AND (canceled_at IS NULL OR canceled_at >= period start).
- For monthly churn trends, calculate per-month: active at start of month vs canceled during that month.
- NEVER use \`status = 'canceled'\` or similar status-based filters for churn. Always use the \`canceled_at\` column.
- For total historical churn, consider all subscriptions where canceled_at IS NOT NULL vs total subscriptions.

IMPORTANT BigQuery SQL Rules:
- Only generate SELECT queries. Do not include any INSERT, UPDATE, DELETE, DROP, or other modifying statements.
- Use the EXACT project ID and dataset provided above. Do not use placeholder values like "your_project".
- MANDATORY CUSTOMER FIELDS: Every query that involves customers or contacts MUST include the customer's name (or first_name/last_name), email, and phone/telephone columns in the SELECT clause if those columns exist in the schema. These fields are required for CRM integration. Even if the user doesn't ask for them explicitly, always include them alongside whatever other data the user requests.
- TIMESTAMP_SUB and TIMESTAMP_ADD only support: MICROSECOND, MILLISECOND, SECOND, MINUTE, HOUR, DAY. They do NOT support MONTH or YEAR.
- For MONTH or YEAR intervals with TIMESTAMP columns, convert months to days (30 days per month): timestamp_column >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 150 DAY) for ~5 months
- NEVER compare TIMESTAMP with DATE directly - they are incompatible types. Either:
  1. Use TIMESTAMP functions for TIMESTAMP columns: timestamp_col >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 60 DAY)
  2. Or cast TIMESTAMP to DATE first: CAST(timestamp_col AS DATE) >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 MONTH)
- Always check the column type in the schema and use matching functions (TIMESTAMP_* for TIMESTAMP, DATE_* for DATE)

DATE RANGE RULES - VERY IMPORTANT:
- By default, DO NOT add any date/time filters to queries. Use ALL available historical data unless the user explicitly asks for a specific time period (e.g., "last 3 months", "in 2024", "since January").
- When the user asks about trends, patterns, or general behavior (e.g., "in what month do users tend to cancel"), you MUST query ALL historical data to get meaningful results. Do NOT limit to recent months.
- Only add date filters when the user explicitly mentions a specific date range or time period.`
        : `You are a retail analytics AI assistant. The user will ask questions about retail data.
Generate a realistic SQL query for BigQuery and provide mock data results that would answer their question.

Respond in JSON format with these fields:
- sql: The SQL query you would run (string)
- summary: A natural language summary of the results (string)  
- data: An array of result objects with realistic retail metrics
- visualizationType: One of "bar", "line", "pie", or "table"

Make the data realistic for a retail business with sales, orders, customers, etc.`;

      if (drillDownSql) {
        systemPrompt += `

SEGMENT DRILL-DOWN MODE:
The user is drilling into a previous result set. You MUST wrap the previous SQL as an inline subquery in the FROM clause — never use a WITH/CTE wrapper because the previous SQL may already contain WITH clauses.
Use this exact pattern:
  SELECT <columns> FROM (<PREVIOUS_SQL_HERE>) AS previous_segment WHERE <new_filter>
Where <PREVIOUS_SQL_HERE> is replaced verbatim with the previous SQL.
The resulting query must be a single valid BigQuery SQL statement.
IMPORTANT: Always preserve customer identity columns (name, first_name, last_name, email, phone) in the SELECT if they exist in previous_segment.`;
      }

      const userMessage = drillDownSql
        ? `DRILL-DOWN: The user already has a segment from this SQL:\n${drillDownSql}\n\nNow they want to further filter/analyze that segment with this question: ${naturalLanguage}`
        : naturalLanguage;

      // Per-attempt timeout of 12s × 2 attempts + 1.5s backoff = ~25.5s total,
      // safely under the 35s global middleware timeout.
      const response = await callOpenAIWithTimeoutAndRetry({
        model: "gpt-4o-mini",
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user", content: userMessage }
        ],
        response_format: { type: "json_object" },
        max_completion_tokens: 2048,
      }, { timeoutMs: 12000, maxRetries: 1 });

      const content = response.choices[0]?.message?.content || "{}";
      let parsedResult;
      try {
        parsedResult = JSON.parse(content);
        if (!parsedResult || typeof parsedResult !== "object") throw new Error("Empty JSON");
      } catch {
        if (res.headersSent) return;
        return res.status(422).json({
          error: "Couldn't understand your question — please try rephrasing it.",
          errorType: "parse_error",
        });
      }

      // Execute against real BigQuery if connection is available
      let resultData = parsedResult.data || [];
      let resultSummary = parsedResult.summary;
      let executionError = null;

      if (bqService && parsedResult.sql) {
        try {
          // Clean the SQL: remove trailing semicolons which cause "multi-statement" errors
          const cleanedSql = parsedResult.sql.replace(/;\s*$/, '').trim();
          const queryResult = await executeQueryWithRetry(bqService, cleanedSql, { maxRows: 2000, timeoutMs: 30000 });
          resultData = queryResult.rows;
          resultSummary = `Query returned ${queryResult.totalRows} rows in ${queryResult.executionTimeMs}ms. ${parsedResult.summary || ""}`;
        } catch (bqError: any) {
          console.error("BigQuery execution error:", bqError.message);
          executionError = bqError.message;
          resultSummary = `Query generation successful but execution failed: ${bqError.message}`;
        }
      }

      const executionTime = Date.now() - startTime;

      const query = await storage.createQuery({
        userId,
        clientId,
        naturalLanguage,
        generatedSql: parsedResult.sql,
        resultSummary,
        resultData: Array.isArray(resultData) ? resultData.slice(0, 500) : resultData,
        visualizationType: parsedResult.visualizationType,
        executionTimeMs: executionTime,
        isSaved: false,
      });

      res.json({
        id: query.id,
        summary: resultSummary,
        data: resultData,
        sql: parsedResult.sql,
        executionTime,
        visualizationType: parsedResult.visualizationType,
        executionError,
        errorType: executionError ? "bigquery_error" : undefined,
        usedRealData: !!bqService && !executionError,
        isSaved: query.isSaved,
      });
    } catch (error: unknown) {
      if (res.headersSent) return;
      console.error("Error processing query:", error);
      if (error instanceof AIServiceError) {
        const msg = isRecommendationIntent
          ? "El servicio de IA no está disponible temporalmente. Por favor intenta en un momento."
          : "AI service is temporarily unavailable. Please try again in a moment.";
        res.status(503).json({ error: msg, errorType: "ai_unavailable" });
      } else {
        res.status(500).json({ error: "Failed to process query. Please try again.", errorType: "unknown" });
      }
    }
  });

  app.get("/api/kpis", isAuthenticatedOrToken, async (req, res) => {
    try {
      const clientId = req.query.clientId ? parseInt(req.query.clientId as string) : null;
      
      const mockKpis = [{
        id: 1,
        clientId: clientId || 1,
        date: new Date(),
        totalSales: "1250000",
        orderCount: 15234,
        averageOrderValue: "82.05",
        recurrenceRate: "34.5",
        newCustomers: 3421,
        recurringCustomers: 5280,
        cartAbandonmentRate: "68.2",
        customerLifetimeValue: "342",
        returnRate: "8.5",
        inventoryTurnover: "4.2",
        rawData: {},
        createdAt: new Date(),
      }];
      
      res.json(mockKpis);
    } catch (error) {
      console.error("Error fetching KPIs:", error);
      res.status(500).json({ error: "Failed to fetch KPIs" });
    }
  });

  app.post("/api/kpis/dashboard", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const { clientId, dateFrom, dateTo } = req.body;

      if (!clientId || !dateFrom || !dateTo) {
        return res.status(400).json({ error: "clientId, dateFrom, and dateTo are required" });
      }

      const hasAccess = await canAccessClient(req, clientId);
      if (!hasAccess) {
        return res.status(404).json({ error: "Client not found" });
      }

      const connection = await storage.getConnectionByClientId(clientId);
      if (!connection) {
        return res.status(400).json({ error: "No BigQuery connection found for this client" });
      }

      const bigqueryService = BigQueryService.fromCredentialsJson(
        connection.projectId,
        connection.credentials,
        connection.datasetId || undefined
      );

      const kpis = await bigqueryService.calculateDashboardKPIs(
        connection.datasetId || "",
        dateFrom,
        dateTo
      );

      res.json({
        ...kpis,
        period: { from: dateFrom, to: dateTo },
        source: "bigquery",
      });
    } catch (error: any) {
      console.error("Error calculating dashboard KPIs:", error);
      res.status(500).json({ error: error.message || "Failed to calculate dashboard KPIs" });
    }
  });

  app.post("/api/kpis/calculate", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const { 
        clientId, 
        dateFrom, 
        dateTo, 
        dateColumn = "created",
        salesTable = "subscriptions",
        salesColumn = "amount",
        customerIdColumn = "customer_id"
      } = req.body;

      if (!clientId || !dateFrom || !dateTo) {
        return res.status(400).json({ error: "clientId, dateFrom, and dateTo are required" });
      }

      const hasAccess = await canAccessClient(req, clientId);
      if (!hasAccess) {
        return res.status(404).json({ error: "Client not found" });
      }

      const connection = await storage.getConnectionByClientId(clientId);
      if (!connection) {
        return res.status(400).json({ error: "No BigQuery connection found for this client" });
      }

      const bigqueryService = BigQueryService.fromCredentialsJson(
        connection.projectId,
        connection.credentials,
        connection.datasetId || undefined
      );

      const kpis = await bigqueryService.calculateKPIs(
        connection.datasetId || "",
        dateFrom,
        dateTo,
        dateColumn,
        salesTable,
        salesColumn,
        customerIdColumn
      );

      const calculateChange = (current: number, previous: number): number => {
        if (previous === 0) return current > 0 ? 100 : 0;
        return ((current - previous) / previous) * 100;
      };

      res.json({
        totalSales: kpis.totalSales,
        orderCount: kpis.orderCount,
        averageOrderValue: kpis.averageOrderValue,
        newCustomers: kpis.newCustomers,
        recurringCustomers: kpis.recurringCustomers,
        recurrenceRate: kpis.recurrenceRate,
        customerLtv: kpis.customerLtv,
        changes: {
          totalSales: calculateChange(kpis.totalSales, kpis.previousPeriod.totalSales),
          orderCount: calculateChange(kpis.orderCount, kpis.previousPeriod.orderCount),
          averageOrderValue: calculateChange(kpis.averageOrderValue, kpis.previousPeriod.averageOrderValue),
          newCustomers: calculateChange(kpis.newCustomers, kpis.previousPeriod.newCustomers),
          recurringCustomers: calculateChange(kpis.recurringCustomers, kpis.previousPeriod.recurringCustomers),
          recurrenceRate: calculateChange(kpis.recurrenceRate, kpis.previousPeriod.recurrenceRate),
          customerLtv: calculateChange(kpis.customerLtv, kpis.previousPeriod.customerLtv),
        },
        period: { from: dateFrom, to: dateTo },
        source: "bigquery",
      });
    } catch (error: any) {
      console.error("Error calculating KPIs:", error);
      res.status(500).json({ error: error.message || "Failed to calculate KPIs" });
    }
  });

  app.post("/api/kpis/trends", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const {
        clientId,
        dateFrom,
        dateTo,
        dateColumn = "created",
        salesTable = "subscriptions",
        salesColumn = "amount",
        customerIdColumn = "customer_id"
      } = req.body;

      if (!clientId || !dateFrom || !dateTo) {
        return res.status(400).json({ error: "clientId, dateFrom, and dateTo are required" });
      }

      const hasAccess = await canAccessClient(req, clientId);
      if (!hasAccess) {
        return res.status(404).json({ error: "Client not found" });
      }

      const connection = await storage.getConnectionByClientId(clientId);
      if (!connection) {
        return res.status(400).json({ error: "No BigQuery connection found for this client" });
      }

      const bigqueryService = BigQueryService.fromCredentialsJson(
        connection.projectId,
        connection.credentials,
        connection.datasetId || undefined
      );

      const trends = await bigqueryService.calculateTrends(
        connection.datasetId || "",
        dateFrom,
        dateTo,
        dateColumn,
        salesTable,
        salesColumn,
        customerIdColumn
      );

      res.json(trends);
    } catch (error: any) {
      console.error("Error calculating trends:", error);
      res.status(500).json({ error: error.message || "Failed to calculate trends" });
    }
  });

  app.post("/api/kpis/product-analytics", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const {
        clientId,
        dateFrom,
        dateTo,
        dateColumn = "created",
        salesTable = "subscriptions",
        salesColumn = "amount",
        customerIdColumn = "customer_id"
      } = req.body;

      if (!clientId || !dateFrom || !dateTo) {
        return res.status(400).json({ error: "clientId, dateFrom, and dateTo are required" });
      }

      const safeIdentifier = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
      const safeDate = /^\d{4}-\d{2}-\d{2}$/;
      for (const [name, val] of Object.entries({ dateColumn, salesTable, salesColumn, customerIdColumn })) {
        if (!safeIdentifier.test(val as string)) {
          return res.status(400).json({ error: `Invalid identifier: ${name}` });
        }
      }
      if (!safeDate.test(dateFrom) || !safeDate.test(dateTo)) {
        return res.status(400).json({ error: "Invalid date format. Use YYYY-MM-DD" });
      }

      const hasAccess = await canAccessClient(req, clientId);
      if (!hasAccess) {
        return res.status(404).json({ error: "Client not found" });
      }

      const connection = await storage.getConnectionByClientId(clientId);
      if (!connection) {
        return res.status(400).json({ error: "No BigQuery connection found for this client" });
      }

      const bigqueryService = BigQueryService.fromCredentialsJson(
        connection.projectId,
        connection.credentials,
        connection.datasetId || undefined
      );

      const productAnalytics = await bigqueryService.calculateProductAnalytics(
        connection.datasetId || "",
        dateFrom,
        dateTo,
        dateColumn,
        salesTable,
        salesColumn,
        customerIdColumn
      );

      res.json(productAnalytics);
    } catch (error: any) {
      console.error("Error calculating product analytics:", error);
      res.status(500).json({ error: error.message || "Failed to calculate product analytics" });
    }
  });

  app.post("/api/kpis/churn-analytics", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const {
        clientId,
        dateFrom,
        dateTo,
        dateColumn = "created",
        salesTable = "subscriptions",
        salesColumn = "amount"
      } = req.body;

      if (!clientId || !dateFrom || !dateTo) {
        return res.status(400).json({ error: "clientId, dateFrom, and dateTo are required" });
      }

      const safeIdentifier = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
      const safeDate = /^\d{4}-\d{2}-\d{2}$/;
      for (const [name, val] of Object.entries({ dateColumn, salesTable, salesColumn })) {
        if (!safeIdentifier.test(val as string)) {
          return res.status(400).json({ error: `Invalid identifier: ${name}` });
        }
      }
      if (!safeDate.test(dateFrom) || !safeDate.test(dateTo)) {
        return res.status(400).json({ error: "Invalid date format. Use YYYY-MM-DD" });
      }

      const hasAccess = await canAccessClient(req, clientId);
      if (!hasAccess) {
        return res.status(404).json({ error: "Client not found" });
      }

      const connection = await storage.getConnectionByClientId(clientId);
      if (!connection) {
        return res.status(400).json({ error: "No BigQuery connection found for this client" });
      }

      const bigqueryService = BigQueryService.fromCredentialsJson(
        connection.projectId,
        connection.credentials,
        connection.datasetId || undefined
      );

      const churnAnalytics = await bigqueryService.calculateChurnAnalytics(
        connection.datasetId || "",
        dateFrom,
        dateTo,
        dateColumn,
        salesTable,
        salesColumn
      );

      res.json(churnAnalytics);
    } catch (error: any) {
      console.error("Error calculating churn analytics:", error);
      res.status(500).json({ error: error.message || "Failed to calculate churn analytics" });
    }
  });

  app.get("/api/exports", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      const exports = await storage.getExports(userId);
      res.json(exports);
    } catch (error) {
      console.error("Error fetching exports:", error);
      res.status(500).json({ error: "Failed to fetch exports" });
    }
  });

  app.post("/api/exports", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const { segmentId, ghlLocationId, ghlTags } = req.body;
      
      const segment = await storage.getSegment(segmentId);
      const contactCount = segment?.contactCount || Math.floor(Math.random() * 1000) + 100;

      const ghlExport = await storage.createExport({
        userId,
        segmentId,
        contactCount,
        status: "processing",
        ghlLocationId,
        ghlTags,
      });

      setTimeout(async () => {
        await storage.updateExport(ghlExport.id, {
          status: "completed",
          completedAt: new Date(),
        });
      }, 3000);

      res.json(ghlExport);
    } catch (error) {
      console.error("Error creating export:", error);
      res.status(500).json({ error: "Failed to create export" });
    }
  });

  // ============================================================
  // GoHighLevel Settings & Contact Sync
  // ============================================================

  app.get("/api/ghl/settings", isAuthenticatedOrToken, async (req, res) => {
    try {
      const ghlApiKey = process.env.GHL_API_KEY;
      const ghlLocationId = process.env.GHL_LOCATION_ID;
      res.json({
        ghlApiKey: ghlApiKey ? "••••••••" + ghlApiKey.slice(-4) : null,
        ghlLocationId: ghlLocationId || null,
        isConfigured: !!(ghlApiKey && ghlLocationId),
      });
    } catch (error) {
      console.error("Error fetching GHL settings:", error);
      res.status(500).json({ error: "Failed to fetch GHL settings" });
    }
  });

  app.post("/api/ghl/send-contacts", isAuthenticatedOrToken, async (req, res) => {
    try {
      const userId = getUserId(req);
      if (!await isAdminUser(req)) return res.status(403).json({ error: "Admin access required" });
      const ghlApiKey = process.env.GHL_API_KEY;
      const ghlLocationId = process.env.GHL_LOCATION_ID;

      if (!ghlApiKey || !ghlLocationId) {
        return res.status(400).json({ 
          error: "GoHighLevel is not configured. Please contact your administrator." 
        });
      }

      const { contacts, tags, segmentId } = req.body;

      if (!contacts || !Array.isArray(contacts) || contacts.length === 0) {
        return res.status(400).json({ error: "No contacts provided" });
      }

      if (contacts.length > 10000) {
        return res.status(400).json({ error: "Maximum 10,000 contacts per batch" });
      }

      const results = { 
        total: contacts.length, 
        created: 0, 
        updated: 0,
        failed: 0, 
        errors: [] as string[] 
      };

      for (const contact of contacts) {
        try {
          const ghlContact: Record<string, any> = {};
          
          if (contact.name) {
            const nameParts = contact.name.trim().split(/\s+/);
            ghlContact.firstName = nameParts[0] || "";
            ghlContact.lastName = nameParts.slice(1).join(" ") || "";
          }
          if (contact.firstName) ghlContact.firstName = contact.firstName;
          if (contact.lastName) ghlContact.lastName = contact.lastName;
          if (contact.email) ghlContact.email = contact.email;
          if (contact.phone) ghlContact.phone = contact.phone;
          if (tags && Array.isArray(tags) && tags.length > 0) {
            ghlContact.tags = tags;
          }

          if (!ghlContact.email && !ghlContact.phone && !ghlContact.firstName) {
            results.failed++;
            continue;
          }

          const response = await fetch(
            `https://services.leadconnectorhq.com/contacts/`,
            {
              method: "POST",
              headers: {
                "Authorization": `Bearer ${ghlApiKey}`,
                "Content-Type": "application/json",
                "Version": "2021-07-28",
              },
              body: JSON.stringify({ ...ghlContact, locationId: ghlLocationId }),
            }
          );

          if (response.ok) {
            const data = await response.json();
            if (data.contact?.id) {
              results.created++;
            } else {
              results.updated++;
            }
          } else {
            const errorData = await response.json().catch(() => ({}));
            results.failed++;
            if (results.errors.length < 5) {
              results.errors.push(
                `Contact ${contact.email || contact.name || "unknown"}: ${errorData.message || response.statusText}`
              );
            }
          }

          // Rate limiting - GHL allows ~100 requests/minute
          await new Promise(resolve => setTimeout(resolve, 650));
        } catch (err: any) {
          results.failed++;
          if (results.errors.length < 5) {
            results.errors.push(err.message || "Unknown error");
          }
        }
      }

      // Log the export in history
      if (segmentId) {
        await storage.createExport({
          userId,
          segmentId,
          contactCount: results.created + results.updated,
          status: results.failed === 0 ? "completed" : "partial",
          ghlLocationId: ghlLocationId,
          ghlTags: tags || [],
        });
      }

      res.json(results);
    } catch (error: any) {
      console.error("Error sending contacts to GHL:", error);
      res.status(500).json({ error: error.message || "Failed to send contacts" });
    }
  });

  // ============================================================
  // Webhook Receiver - Incoming customers from BigQuery
  // ============================================================

  app.post("/api/webhooks/new-customers", async (req, res) => {
    try {
      const webhookSecret = process.env.WEBHOOK_SECRET;
      if (webhookSecret) {
        const authHeader = req.headers["x-webhook-secret"] || req.headers["authorization"];
        const providedSecret = typeof authHeader === "string" 
          ? authHeader.replace("Bearer ", "") 
          : "";
        if (providedSecret !== webhookSecret) {
          return res.status(401).json({ error: "Unauthorized: invalid webhook secret" });
        }
      }

      const ghlApiKey = process.env.GHL_API_KEY;
      const ghlLocationId = process.env.GHL_LOCATION_ID;

      if (!ghlApiKey || !ghlLocationId) {
        return res.status(500).json({ error: "GoHighLevel is not configured on this server" });
      }

      const { customers, tags } = req.body;

      const customerList = customers || (req.body.customer ? [req.body.customer] : null);

      if (!customerList || !Array.isArray(customerList) || customerList.length === 0) {
        return res.status(400).json({ 
          error: "No customers provided. Send { customers: [...] } or { customer: {...} }",
          expected_format: {
            customers: [
              { customer_id: "cus_123", email: "john@example.com", name: "John Doe", phone: "+1234567890", product_id: "prod_LQjx67EvzQ1PGQ" }
            ],
            tags: ["New Customer"]
          }
        });
      }

      if (customerList.length > 10000) {
        return res.status(400).json({ error: "Maximum 10,000 customers per request" });
      }

      const productMap: Record<string, string> = {
        "prod_LQjx67EvzQ1PGQ": "Basic Wash",
        "prod_LQjy3uY1m2leN3": "Premium Wash",
        "prod_QokBj7SE3bnVgn": "BW/Road Assistance",
        "prod_TEj2sqBLZUBBby": "BW/Road Assistance Yearly",
      };

      console.log(`[Webhook] Received ${customerList.length} customer(s) from BigQuery`);

      const results = {
        total: customerList.length,
        created: 0,
        updated: 0,
        failed: 0,
        errors: [] as string[],
        timestamp: new Date().toISOString(),
      };

      for (const contact of customerList) {
        try {
          const ghlContact: Record<string, any> = {};

          if (contact.name) {
            const nameParts = contact.name.trim().split(/\s+/);
            ghlContact.firstName = nameParts[0] || "";
            ghlContact.lastName = nameParts.slice(1).join(" ") || "";
          }
          if (contact.firstName || contact.first_name) ghlContact.firstName = contact.firstName || contact.first_name;
          if (contact.lastName || contact.last_name) ghlContact.lastName = contact.lastName || contact.last_name;
          if (contact.email) ghlContact.email = contact.email;
          if (contact.phone) ghlContact.phone = contact.phone;

          const contactTags: string[] = [];
          if (tags && Array.isArray(tags) && tags.length > 0) {
            contactTags.push(...tags);
          }
          if (contact.product_id) {
            const productName = productMap[contact.product_id] || contact.product_id;
            contactTags.push(productName);
          }
          if (contact.tags && Array.isArray(contact.tags)) {
            contactTags.push(...contact.tags);
          }
          if (contactTags.length > 0) {
            ghlContact.tags = contactTags;
          }

          if (!ghlContact.email && !ghlContact.phone && !ghlContact.firstName) {
            results.failed++;
            if (results.errors.length < 10) {
              results.errors.push(`Contact ${contact.customer_id || "unknown"} skipped: no email, phone, or name`);
            }
            continue;
          }

          const response = await fetch(
            `https://services.leadconnectorhq.com/contacts/`,
            {
              method: "POST",
              headers: {
                "Authorization": `Bearer ${ghlApiKey}`,
                "Content-Type": "application/json",
                "Version": "2021-07-28",
              },
              body: JSON.stringify({ ...ghlContact, locationId: ghlLocationId }),
            }
          );

          if (response.ok) {
            const data = await response.json();
            if (data.contact?.id) {
              results.created++;
            } else {
              results.updated++;
            }
          } else {
            const errorData = await response.json().catch(() => ({}));
            results.failed++;
            if (results.errors.length < 10) {
              results.errors.push(
                `Contact ${contact.email || contact.name || "unknown"}: ${errorData.message || response.statusText}`
              );
            }
          }

          await new Promise(resolve => setTimeout(resolve, 650));
        } catch (err: any) {
          results.failed++;
          if (results.errors.length < 10) {
            results.errors.push(err.message || "Unknown error");
          }
        }
      }

      console.log(`[Webhook] Finished: ${results.created} created, ${results.updated} updated, ${results.failed} failed`);

      res.json(results);
    } catch (error: any) {
      console.error("[Webhook] Error processing incoming customers:", error);
      res.status(500).json({ error: error.message || "Failed to process incoming customers" });
    }
  });

  // Text-to-Speech endpoint
  app.post("/api/speak", isAuthenticatedOrToken, async (req, res) => {
    try {
      const { text, voice = "alloy" } = req.body;
      
      if (!text) {
        return res.status(400).json({ error: "No text provided" });
      }

      // Limit text length to prevent abuse
      const truncatedText = text.slice(0, 2000);
      
      // Generate speech
      const audioBuffer = await textToSpeech(truncatedText, voice, "mp3");
      
      // Return as base64 for easy client-side playback
      res.json({ 
        audio: audioBuffer.toString("base64"),
        format: "mp3"
      });
    } catch (error) {
      console.error("Error generating speech:", error);
      res.status(500).json({ error: "Failed to generate speech" });
    }
  });

  // Voice transcription endpoint
  app.post("/api/transcribe", isAuthenticatedOrToken, async (req, res) => {
    try {
      const { audio } = req.body;
      
      if (!audio) {
        return res.status(400).json({ error: "No audio data provided" });
      }

      // Decode base64 audio
      const audioBuffer = Buffer.from(audio, "base64");
      
      // Convert WebM to WAV for transcription
      const wavBuffer = await convertWebmToWav(audioBuffer);
      
      // Transcribe using OpenAI
      const transcript = await speechToText(wavBuffer, "wav");
      
      res.json({ transcript });
    } catch (error) {
      console.error("Error transcribing audio:", error);
      res.status(500).json({ error: "Failed to transcribe audio" });
    }
  });

  // ============================================================
  // Page Builder API
  // ============================================================

  // Pages
  app.get("/api/pages", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const pages = await storage.getPages(userId);
      res.json(pages);
    } catch (error) {
      console.error("Error fetching pages:", error);
      res.status(500).json({ error: "Failed to fetch pages" });
    }
  });

  app.get("/api/pages/:id", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const page = await storage.getPage(id);
      if (!page) {
        return res.status(404).json({ error: "Page not found" });
      }
      if (page.userId !== userId) {
        return res.status(403).json({ error: "Access denied" });
      }
      res.json(page);
    } catch (error) {
      console.error("Error fetching page:", error);
      res.status(500).json({ error: "Failed to fetch page" });
    }
  });

  app.post("/api/pages", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const { name, slug, clientId } = req.body;
      
      const page = await storage.createPage({
        userId,
        name,
        slug: slug || name.toLowerCase().replace(/\s+/g, '-'),
        clientId,
        isPublished: false,
      });

      // Create initial version
      const version = await storage.createPageVersion({
        pageId: page.id,
        versionName: "Version 1",
        versionNumber: 1,
        isActive: true,
      });

      res.json({ ...page, activeVersionId: version.id });
    } catch (error) {
      console.error("Error creating page:", error);
      res.status(500).json({ error: "Failed to create page" });
    }
  });

  app.put("/api/pages/:id", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const existingPage = await storage.getPage(id);
      if (!existingPage) {
        return res.status(404).json({ error: "Page not found" });
      }
      if (existingPage.userId !== userId) {
        return res.status(403).json({ error: "Access denied" });
      }
      const page = await storage.updatePage(id, req.body);
      res.json(page);
    } catch (error) {
      console.error("Error updating page:", error);
      res.status(500).json({ error: "Failed to update page" });
    }
  });

  app.delete("/api/pages/:id", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const existingPage = await storage.getPage(id);
      if (!existingPage) {
        return res.status(404).json({ error: "Page not found" });
      }
      if (existingPage.userId !== userId) {
        return res.status(403).json({ error: "Access denied" });
      }
      await storage.deletePage(id);
      res.json({ success: true });
    } catch (error) {
      console.error("Error deleting page:", error);
      res.status(500).json({ error: "Failed to delete page" });
    }
  });

  // Helper to verify page ownership
  async function verifyPageOwnership(pageId: number, userId: string): Promise<boolean> {
    const page = await storage.getPage(pageId);
    return page?.userId === userId;
  }

  // Page Versions
  app.get("/api/pages/:pageId/versions", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const pageId = parseInt(req.params.pageId as string);
      if (!await verifyPageOwnership(pageId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }
      const versions = await storage.getPageVersions(pageId);
      res.json(versions);
    } catch (error) {
      console.error("Error fetching versions:", error);
      res.status(500).json({ error: "Failed to fetch versions" });
    }
  });

  app.post("/api/pages/:pageId/versions", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const pageId = parseInt(req.params.pageId as string);
      if (!await verifyPageOwnership(pageId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }
      const existingVersions = await storage.getPageVersions(pageId);
      const nextNumber = existingVersions.length + 1;

      const version = await storage.createPageVersion({
        pageId,
        versionName: req.body.versionName || `Version ${nextNumber}`,
        versionNumber: nextNumber,
        isActive: false,
      });

      res.json(version);
    } catch (error) {
      console.error("Error creating version:", error);
      res.status(500).json({ error: "Failed to create version" });
    }
  });

  app.put("/api/versions/:id/activate", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const version = await storage.getPageVersion(id);
      if (!version) {
        return res.status(404).json({ error: "Version not found" });
      }
      if (!await verifyPageOwnership(version.pageId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }

      // Deactivate all other versions for this page
      const allVersions = await storage.getPageVersions(version.pageId);
      for (const v of allVersions) {
        if (v.id !== id) {
          await storage.updatePageVersion(v.id, { isActive: false });
        }
      }

      // Activate this version
      const updated = await storage.updatePageVersion(id, { isActive: true });
      res.json(updated);
    } catch (error) {
      console.error("Error activating version:", error);
      res.status(500).json({ error: "Failed to activate version" });
    }
  });

  const updateVersionContentSchema = z.object({
    htmlContent: z.string().max(500000).optional(),
    cssContent: z.string().max(100000).optional(),
    gjsComponents: z.any().optional(),
    gjsStyles: z.any().optional(),
  });

  app.put("/api/versions/:id", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const version = await storage.getPageVersion(id);
      if (!version) {
        return res.status(404).json({ error: "Version not found" });
      }
      if (!await verifyPageOwnership(version.pageId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }

      const parsed = updateVersionContentSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ error: "Invalid request data", details: parsed.error.errors });
      }

      const { htmlContent, cssContent, gjsComponents, gjsStyles } = parsed.data;
      const updated = await storage.updatePageVersion(id, {
        htmlContent,
        cssContent,
        gjsComponents,
        gjsStyles,
      });
      res.json(updated);
    } catch (error) {
      console.error("Error updating version:", error);
      res.status(500).json({ error: "Failed to update version" });
    }
  });

  app.delete("/api/versions/:id", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const version = await storage.getPageVersion(id);
      if (!version) {
        return res.status(404).json({ error: "Version not found" });
      }
      if (!await verifyPageOwnership(version.pageId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }
      await storage.deletePageVersion(id);
      res.json({ success: true });
    } catch (error) {
      console.error("Error deleting version:", error);
      res.status(500).json({ error: "Failed to delete version" });
    }
  });

  // Helper to verify version ownership via its parent page
  async function verifyVersionOwnership(versionId: number, userId: string): Promise<boolean> {
    const version = await storage.getPageVersion(versionId);
    if (!version) return false;
    return verifyPageOwnership(version.pageId, userId);
  }

  // Page Sections
  app.get("/api/versions/:versionId/sections", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const versionId = parseInt(req.params.versionId as string);
      if (!await verifyVersionOwnership(versionId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }
      const sections = await storage.getPageSections(versionId);
      res.json(sections);
    } catch (error) {
      console.error("Error fetching sections:", error);
      res.status(500).json({ error: "Failed to fetch sections" });
    }
  });

  app.post("/api/versions/:versionId/sections", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const versionId = parseInt(req.params.versionId as string);
      if (!await verifyVersionOwnership(versionId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }
      const existingSections = await storage.getPageSections(versionId);
      const nextOrder = existingSections.length;

      const section = await storage.createPageSection({
        versionId,
        sectionType: req.body.sectionType,
        sectionOrder: nextOrder,
        content: req.body.content || {},
        styles: req.body.styles || {},
        isVisible: true,
      });

      res.json(section);
    } catch (error) {
      console.error("Error creating section:", error);
      res.status(500).json({ error: "Failed to create section" });
    }
  });

  app.put("/api/sections/:id", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const section = await storage.getPageSection(id);
      if (!section) {
        return res.status(404).json({ error: "Section not found" });
      }
      if (!await verifyVersionOwnership(section.versionId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }
      const updated = await storage.updatePageSection(id, req.body);
      res.json(updated);
    } catch (error) {
      console.error("Error updating section:", error);
      res.status(500).json({ error: "Failed to update section" });
    }
  });

  app.delete("/api/sections/:id", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const section = await storage.getPageSection(id);
      if (!section) {
        return res.status(404).json({ error: "Section not found" });
      }
      if (!await verifyVersionOwnership(section.versionId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }
      await storage.deletePageSection(id);
      res.json({ success: true });
    } catch (error) {
      console.error("Error deleting section:", error);
      res.status(500).json({ error: "Failed to delete section" });
    }
  });

  app.post("/api/versions/:versionId/sections/reorder", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const versionId = parseInt(req.params.versionId as string);
      if (!await verifyVersionOwnership(versionId, userId)) {
        return res.status(403).json({ error: "Access denied" });
      }
      const { sectionIds } = req.body;
      
      // Validate that all sectionIds belong to this version
      const existingSections = await storage.getPageSections(versionId);
      const validIds = new Set(existingSections.map(s => s.id));
      const invalidIds = sectionIds.filter((id: number) => !validIds.has(id));
      if (invalidIds.length > 0) {
        return res.status(400).json({ error: "Invalid section IDs" });
      }
      
      await storage.reorderSections(versionId, sectionIds);
      res.json({ success: true });
    } catch (error) {
      console.error("Error reordering sections:", error);
      res.status(500).json({ error: "Failed to reorder sections" });
    }
  });

  // Section Templates
  app.get("/api/section-templates", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const templates = await storage.getSectionTemplates(userId);
      res.json(templates);
    } catch (error) {
      console.error("Error fetching templates:", error);
      res.status(500).json({ error: "Failed to fetch templates" });
    }
  });

  app.post("/api/section-templates", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const template = await storage.createSectionTemplate({
        userId,
        name: req.body.name,
        sectionType: req.body.sectionType,
        content: req.body.content || {},
        styles: req.body.styles || {},
        thumbnailUrl: req.body.thumbnailUrl,
        isSystem: false,
      });
      res.json(template);
    } catch (error) {
      console.error("Error creating template:", error);
      res.status(500).json({ error: "Failed to create template" });
    }
  });

  app.delete("/api/section-templates/:id", isAuthenticated, async (req, res) => {
    try {
      const userId = getUserId(req);
      const id = parseInt(req.params.id as string);
      const template = await storage.getSectionTemplate(id);
      if (!template) {
        return res.status(404).json({ error: "Template not found" });
      }
      if (template.isSystem) {
        return res.status(403).json({ error: "Cannot delete system templates" });
      }
      if (template.userId !== userId) {
        return res.status(403).json({ error: "Access denied" });
      }
      await storage.deleteSectionTemplate(id);
      res.json({ success: true });
    } catch (error) {
      console.error("Error deleting template:", error);
      res.status(500).json({ error: "Failed to delete template" });
    }
  });

  return httpServer;
}
