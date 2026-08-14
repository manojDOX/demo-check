import { users, type User, type UpsertUser } from "@shared/models/auth";
import { teamMembers } from "@shared/schema";
import { db } from "../../db";
import { eq, and } from "drizzle-orm";

// Interface for auth storage operations
// (IMPORTANT) These user operations are mandatory for Replit Auth.
export interface IAuthStorage {
  getUser(id: string): Promise<User | undefined>;
  upsertUser(user: UpsertUser): Promise<User>;
}

class AuthStorage implements IAuthStorage {
  async getUser(id: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.id, id));
    return user;
  }

  async upsertUser(userData: UpsertUser): Promise<User> {
    const existingUser = await this.getUser(userData.id as string);
    
    if (existingUser) {
      const updateData: Partial<UpsertUser> = {
        email: userData.email,
        firstName: userData.firstName,
        lastName: userData.lastName,
        updatedAt: new Date(),
      };
      if (!existingUser.profileImageUrl && userData.profileImageUrl) {
        updateData.profileImageUrl = userData.profileImageUrl;
      }
      const [user] = await db
        .update(users)
        .set(updateData)
        .where(eq(users.id, existingUser.id))
        .returning();

      if (userData.email) {
        await this.linkPendingTeamMemberships(user.id, userData.email);
      }

      return user;
    }
    
    const [user] = await db
      .insert(users)
      .values(userData)
      .returning();

    if (userData.email) {
      await this.linkPendingTeamMemberships(user.id, userData.email);
    }

    return user;
  }

  private async linkPendingTeamMemberships(userId: string, email: string): Promise<void> {
    try {
      await db
        .update(teamMembers)
        .set({ userId, status: "active" })
        .where(
          and(
            eq(teamMembers.email, email.toLowerCase()),
            eq(teamMembers.status, "pending")
          )
        );
    } catch (error) {
      console.error("Error linking pending team memberships:", error);
    }
  }
}

export const authStorage = new AuthStorage();
