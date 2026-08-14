import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTheme } from "@/lib/theme-provider";
import { useToast } from "@/hooks/use-toast";
import { useRole } from "@/hooks/use-role";
import { apiRequest, queryClient } from "@/lib/queryClient";
import type { Client } from "@shared/schema";
import {
  Settings as SettingsIcon,
  User,
  Bell,
  Palette,
  Shield,
  Key,
  Moon,
  Sun,
  Save,
  ExternalLink,
  CheckCircle2,
  Loader2,
  Camera,
  Users,
  UserPlus,
  Trash2,
  Mail,
  Building2,
  Copy,
  Link,
  Bot,
  Eye,
  EyeOff,
  Plus,
} from "lucide-react";

interface UserProfile {
  id: string;
  email: string | null;
  firstName: string | null;
  lastName: string | null;
  company: string | null;
  profileImageUrl: string | null;
}

interface TeamMemberWithClients {
  id: number;
  adminUserId: string;
  email: string;
  role: string;
  status: string;
  userId: string | null;
  shareToken: string | null;
  createdAt: string;
  assignedClientIds: number[];
}

function TeamManagement() {
  const { toast } = useToast();
  const [inviteEmail, setInviteEmail] = useState("");
  const [selectedClientIds, setSelectedClientIds] = useState<number[]>([]);

  const { data: teamMembers, isLoading: isLoadingTeam } = useQuery<TeamMemberWithClients[]>({
    queryKey: ["/api/team"],
  });

  const { data: allClients, isLoading: isLoadingClients } = useQuery<Client[]>({
    queryKey: ["/api/clients"],
  });

  const inviteMutation = useMutation({
    mutationFn: async () => {
      const response = await apiRequest("POST", "/api/team", {
        email: inviteEmail,
        clientIds: selectedClientIds,
      });
      return response.json();
    },
    onSuccess: () => {
      toast({ title: "Collaborator invited", description: `Invitation sent to ${inviteEmail}` });
      setInviteEmail("");
      setSelectedClientIds([]);
      queryClient.invalidateQueries({ queryKey: ["/api/team"] });
    },
    onError: (error: any) => {
      toast({ title: "Error", description: error.message || "Failed to invite collaborator", variant: "destructive" });
    },
  });

  const removeMutation = useMutation({
    mutationFn: async (memberId: number) => {
      await apiRequest("DELETE", `/api/team/${memberId}`);
    },
    onSuccess: () => {
      toast({ title: "Collaborator removed" });
      queryClient.invalidateQueries({ queryKey: ["/api/team"] });
    },
    onError: (error: any) => {
      toast({ title: "Error", description: error.message || "Failed to remove collaborator", variant: "destructive" });
    },
  });

  const updateClientsMutation = useMutation({
    mutationFn: async ({ memberId, clientIds }: { memberId: number; clientIds: number[] }) => {
      const response = await apiRequest("PATCH", `/api/team/${memberId}`, { clientIds });
      return response.json();
    },
    onSuccess: () => {
      toast({ title: "Client access updated" });
      queryClient.invalidateQueries({ queryKey: ["/api/team"] });
    },
    onError: (error: any) => {
      toast({ title: "Error", description: error.message || "Failed to update access", variant: "destructive" });
    },
  });

  const toggleClientForInvite = (clientId: number) => {
    setSelectedClientIds(prev =>
      prev.includes(clientId) ? prev.filter(id => id !== clientId) : [...prev, clientId]
    );
  };

  const toggleClientForMember = (member: TeamMemberWithClients, clientId: number) => {
    const current = member.assignedClientIds;
    const updated = current.includes(clientId)
      ? current.filter(id => id !== clientId)
      : [...current, clientId];
    if (updated.length === 0) {
      toast({ title: "Error", description: "At least one client must be assigned", variant: "destructive" });
      return;
    }
    updateClientsMutation.mutate({ memberId: member.id, clientIds: updated });
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserPlus className="h-5 w-5" />
            Invite Collaborator
          </CardTitle>
          <CardDescription>
            Add team members who can view Dashboard, Ask your Data, and KPI Analytics for specific clients
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="inviteEmail">Email Address</Label>
            <div className="flex gap-2">
              <Input
                id="inviteEmail"
                type="email"
                placeholder="collaborator@example.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                data-testid="input-invite-email"
              />
            </div>
          </div>

          {allClients && allClients.length > 0 && (
            <div className="space-y-2">
              <Label>Assign Clients</Label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {allClients.map((client) => (
                  <label
                    key={client.id}
                    className="flex items-center gap-2 p-2 rounded-md border border-border hover:bg-muted/50 cursor-pointer transition-colors"
                    data-testid={`checkbox-invite-client-${client.id}`}
                  >
                    <Checkbox
                      checked={selectedClientIds.includes(client.id)}
                      onCheckedChange={() => toggleClientForInvite(client.id)}
                    />
                    <div className="flex items-center gap-2">
                      <div
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: client.primaryColor || "#3B82F6" }}
                      />
                      <span className="text-sm">{client.name}</span>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}

          <Button
            onClick={() => inviteMutation.mutate()}
            disabled={!inviteEmail || selectedClientIds.length === 0 || inviteMutation.isPending}
            className="gap-2"
            data-testid="button-invite"
          >
            {inviteMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <UserPlus className="h-4 w-4" />
            )}
            Invite
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Team Members
          </CardTitle>
          <CardDescription>
            Manage your team's access to client data
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoadingTeam ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading team...
            </div>
          ) : !teamMembers || teamMembers.length === 0 ? (
            <p className="text-sm text-muted-foreground">No team members yet. Invite someone above.</p>
          ) : (
            <div className="space-y-4">
              {teamMembers.map((member) => (
                <div
                  key={member.id}
                  className="flex flex-col gap-3 p-4 rounded-lg border border-border"
                  data-testid={`team-member-${member.id}`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10">
                        <Mail className="h-4 w-4 text-primary" />
                      </div>
                      <div>
                        <p className="font-medium text-sm" data-testid={`text-member-email-${member.id}`}>{member.email}</p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <Badge variant={member.status === "active" ? "default" : "secondary"} className="text-xs">
                            {member.status === "active" ? "Active" : "Pending"}
                          </Badge>
                          <span className="text-xs text-muted-foreground">Viewer</span>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      {member.shareToken && (
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => {
                            const shareUrl = `${window.location.origin}/api/shared/${member.shareToken}`;
                            navigator.clipboard.writeText(shareUrl);
                            toast({ title: "Enlace copiado", description: "El enlace de acceso ha sido copiado al portapapeles" });
                          }}
                          title="Copiar enlace de acceso"
                          data-testid={`button-copy-link-${member.id}`}
                        >
                          <Link className="h-4 w-4 text-primary" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => removeMutation.mutate(member.id)}
                        disabled={removeMutation.isPending}
                        data-testid={`button-remove-member-${member.id}`}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>

                  {allClients && allClients.length > 0 && (
                    <div className="pl-12">
                      <p className="text-xs text-muted-foreground mb-1.5 flex items-center gap-1">
                        <Building2 className="h-3 w-3" />
                        Assigned Clients
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {allClients.map((client) => {
                          const isAssigned = member.assignedClientIds.includes(client.id);
                          return (
                            <button
                              key={client.id}
                              onClick={() => toggleClientForMember(member, client.id)}
                              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs border transition-colors ${
                                isAssigned
                                  ? "bg-primary/10 border-primary/30 text-primary"
                                  : "border-border text-muted-foreground hover:bg-muted/50"
                              }`}
                              data-testid={`toggle-client-${member.id}-${client.id}`}
                            >
                              <div
                                className="h-2 w-2 rounded-full"
                                style={{ backgroundColor: client.primaryColor || "#3B82F6" }}
                              />
                              {client.name}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
}

interface ChatbotTokenSummary {
  id: string;
  ownerUserId: string;
  provider: string;
  model: string;
  availableModels: string[];
  displayName: string | null;
  isActive: boolean;
  createdAt: string;
  llmApiToken: string;
}

const LLM_PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "gemini", label: "Google Gemini" },
  { value: "groq", label: "Groq" },
  { value: "openrouter", label: "OpenRouter" },
];

function providerLabel(provider: string): string {
  return LLM_PROVIDERS.find((p) => p.value === provider)?.label || provider;
}

function AiProviderSettings() {
  const { toast } = useToast();
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);

  const { data: tokens, isLoading } = useQuery<ChatbotTokenSummary[]>({
    queryKey: ["/api/chat/tokens"],
  });

  const addTokenMutation = useMutation({
    mutationFn: async () => {
      const response = await apiRequest("POST", "/api/chat/tokens", {
        provider,
        apiKey,
        displayName: displayName.trim() || undefined,
      });
      return response.json();
    },
    onSuccess: () => {
      toast({ title: "API key added", description: "Your key was validated and saved." });
      queryClient.invalidateQueries({ queryKey: ["/api/chat/tokens"] });
      setApiKey("");
      setDisplayName("");
    },
    onError: (error: any) => {
      toast({
        title: "Couldn't validate that key",
        description: error.message || "The provider rejected this API key.",
        variant: "destructive",
      });
    },
  });

  const updateTokenMutation = useMutation({
    mutationFn: async ({ id, model }: { id: string; model: string }) => {
      const response = await apiRequest("PATCH", `/api/chat/tokens/${id}`, { model });
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/chat/tokens"] });
    },
    onError: (error: any) => {
      toast({ title: "Error", description: error.message || "Failed to update model", variant: "destructive" });
    },
  });

  const deleteTokenMutation = useMutation({
    mutationFn: async (id: string) => {
      await apiRequest("DELETE", `/api/chat/tokens/${id}`);
    },
    onSuccess: () => {
      toast({ title: "API key removed" });
      queryClient.invalidateQueries({ queryKey: ["/api/chat/tokens"] });
    },
    onError: (error: any) => {
      toast({ title: "Error", description: error.message || "Failed to remove key", variant: "destructive" });
    },
  });

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5" />
            Add LLM API Key
          </CardTitle>
          <CardDescription>
            Bring your own key from a supported provider to power "Ask Your Data". Keys are validated
            live against the provider and stored encrypted — the raw key is never shown again.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="llm-provider">Provider</Label>
              <Select value={provider} onValueChange={setProvider}>
                <SelectTrigger id="llm-provider" data-testid="select-llm-provider">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LLM_PROVIDERS.map((p) => (
                    <SelectItem key={p.value} value={p.value} data-testid={`select-llm-provider-${p.value}`}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="llm-display-name">Display Name (optional)</Label>
              <Input
                id="llm-display-name"
                placeholder="e.g., Personal OpenAI key"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                data-testid="input-llm-display-name"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="llm-api-key">API Key</Label>
            <div className="flex gap-2">
              <Input
                id="llm-api-key"
                type={showApiKey ? "text" : "password"}
                placeholder="Paste your API key..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                data-testid="input-llm-api-key"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => setShowApiKey(!showApiKey)}
                data-testid="button-toggle-llm-api-key"
              >
                {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>
          </div>
          <Button
            className="gap-2"
            onClick={() => addTokenMutation.mutate()}
            disabled={!apiKey.trim() || addTokenMutation.isPending}
            data-testid="button-add-llm-key"
          >
            {addTokenMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            {addTokenMutation.isPending ? "Validating..." : "Validate & Save"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Key className="h-5 w-5" />
            Your API Keys
          </CardTitle>
          <CardDescription>Manage the LLM keys available to "Ask Your Data"</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading keys...
            </div>
          ) : !tokens || tokens.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No API keys yet. Add one above to start using "Ask Your Data".
            </p>
          ) : (
            <div className="space-y-3">
              {tokens.map((token) => (
                <div
                  key={token.id}
                  className="flex flex-col gap-3 p-4 rounded-lg border border-border sm:flex-row sm:items-center sm:justify-between"
                  data-testid={`llm-token-${token.id}`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 shrink-0">
                      <Bot className="h-4 w-4 text-primary" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-medium text-sm truncate">
                          {token.displayName || providerLabel(token.provider)}
                        </p>
                        <Badge variant="secondary" className="text-xs">{providerLabel(token.provider)}</Badge>
                        {token.isActive && (
                          <Badge variant="default" className="text-xs gap-1">
                            <CheckCircle2 className="h-3 w-3" />
                            Active
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">Key: {token.llmApiToken}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {token.availableModels && token.availableModels.length > 1 ? (
                      <Select
                        value={token.model}
                        onValueChange={(model: string) => updateTokenMutation.mutate({ id: token.id, model })}
                      >
                        <SelectTrigger className="w-[200px]" data-testid={`select-llm-model-${token.id}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {token.availableModels.map((m) => (
                            <SelectItem key={m} value={m}>{m}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Badge variant="outline" className="font-mono text-xs">{token.model}</Badge>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => deleteTokenMutation.mutate(token.id)}
                      disabled={deleteTokenMutation.isPending}
                      data-testid={`button-delete-llm-key-${token.id}`}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
}

export default function Settings() {
  const { theme, setTheme } = useTheme();
  const { toast } = useToast();
  const { isAdmin } = useRole();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const [notifications, setNotifications] = useState({
    email: true,
    queryComplete: true,
    segmentUpdates: true,
    exportStatus: true,
  });

  const { data: profile, isLoading: isLoadingProfile } = useQuery<UserProfile>({
    queryKey: ["/api/profile"],
  });

  useEffect(() => {
    if (profile) {
      setFirstName(profile.firstName || "");
      setLastName(profile.lastName || "");
      setEmail(profile.email || "");
      setCompany(profile.company || "");
    }
  }, [profile]);

  const saveProfileMutation = useMutation({
    mutationFn: async () => {
      const response = await apiRequest("PATCH", "/api/profile", {
        firstName,
        lastName,
        email,
        company,
      });
      return response.json();
    },
    onSuccess: () => {
      toast({ title: "Profile updated", description: "Your profile has been saved successfully." });
      queryClient.invalidateQueries({ queryKey: ["/api/profile"] });
      queryClient.invalidateQueries({ queryKey: ["/api/auth/user"] });
    },
    onError: (error: any) => {
      toast({ title: "Error", description: error.message || "Failed to save profile", variant: "destructive" });
    },
  });

  const uploadAvatarMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("avatar", file);
      const response = await fetch("/api/profile/avatar", {
        method: "POST",
        body: formData,
        credentials: "include",
      });
      if (!response.ok) throw new Error("Upload failed");
      return response.json();
    },
    onSuccess: () => {
      toast({ title: "Avatar updated", description: "Your profile picture has been updated." });
      queryClient.invalidateQueries({ queryKey: ["/api/profile"] });
      queryClient.invalidateQueries({ queryKey: ["/api/auth/user"] });
    },
    onError: (error: any) => {
      toast({ title: "Error", description: error.message || "Failed to upload avatar", variant: "destructive" });
    },
  });

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadAvatarMutation.mutate(file);
  };


  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <SettingsIcon className="h-6 w-6 text-primary" />
          Settings
        </h1>
        <p className="text-muted-foreground mt-1">
          Manage your account and platform preferences
        </p>
      </div>

      <Tabs defaultValue="integrations" className="space-y-6">
        <TabsList className="bg-muted p-1">
          <TabsTrigger value="integrations" className="gap-2" data-testid="tab-integrations">
            <ExternalLink className="h-4 w-4" />
            Integrations
          </TabsTrigger>
          <TabsTrigger value="ai-provider" className="gap-2" data-testid="tab-ai-provider">
            <Bot className="h-4 w-4" />
            AI Provider
          </TabsTrigger>
          {isAdmin && (
            <TabsTrigger value="team" className="gap-2" data-testid="tab-team">
              <Users className="h-4 w-4" />
              Team
            </TabsTrigger>
          )}
          <TabsTrigger value="profile" className="gap-2" data-testid="tab-profile">
            <User className="h-4 w-4" />
            Profile
          </TabsTrigger>
          <TabsTrigger value="appearance" className="gap-2" data-testid="tab-appearance">
            <Palette className="h-4 w-4" />
            Appearance
          </TabsTrigger>
          <TabsTrigger value="notifications" className="gap-2" data-testid="tab-notifications">
            <Bell className="h-4 w-4" />
            Notifications
          </TabsTrigger>
          <TabsTrigger value="security" className="gap-2" data-testid="tab-security">
            <Shield className="h-4 w-4" />
            Security
          </TabsTrigger>
        </TabsList>

        <TabsContent value="integrations" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div>
                  <CardTitle>GoHighLevel CRM</CardTitle>
                  <CardDescription>
                    Send customer segments directly to GoHighLevel as contacts
                  </CardDescription>
                </div>
                <Badge variant="secondary" className="gap-1">
                  <CheckCircle2 className="h-3 w-3" />
                  Connected
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                GoHighLevel integration is configured and managed by your administrator. 
                You can send customer segments to GHL from the Export page or directly from query results.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="ai-provider" className="space-y-6">
          <AiProviderSettings />
        </TabsContent>

        {isAdmin && (
          <TabsContent value="team" className="space-y-6">
            <TeamManagement />
          </TabsContent>
        )}

        <TabsContent value="profile" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Profile Information</CardTitle>
              <CardDescription>
                Update your account details and preferences
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {isLoadingProfile ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading profile...
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-6">
                    <div className="relative">
                      <Avatar className="h-20 w-20">
                        <AvatarImage src={profile?.profileImageUrl ? `${profile.profileImageUrl}?t=${Date.now()}` : undefined} />
                        <AvatarFallback className="text-lg">
                          {(profile?.firstName?.[0] || "").toUpperCase()}{(profile?.lastName?.[0] || "").toUpperCase() || <User className="h-8 w-8" />}
                        </AvatarFallback>
                      </Avatar>
                      <Button
                        size="icon"
                        variant="secondary"
                        className="absolute -bottom-1 -right-1 h-8 w-8 rounded-full"
                        onClick={() => avatarInputRef.current?.click()}
                        disabled={uploadAvatarMutation.isPending}
                        data-testid="button-upload-avatar"
                      >
                        {uploadAvatarMutation.isPending ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Camera className="h-3 w-3" />
                        )}
                      </Button>
                      <input
                        ref={avatarInputRef}
                        type="file"
                        accept="image/jpeg,image/png,image/gif,image/webp"
                        className="hidden"
                        onChange={handleAvatarChange}
                        data-testid="input-avatar-file"
                      />
                    </div>
                    <div>
                      <p className="font-medium">{firstName} {lastName}</p>
                      <p className="text-sm text-muted-foreground">{email}</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="firstName">First Name</Label>
                      <Input
                        id="firstName"
                        placeholder="John"
                        value={firstName}
                        onChange={(e) => setFirstName(e.target.value)}
                        data-testid="input-first-name"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="lastName">Last Name</Label>
                      <Input
                        id="lastName"
                        placeholder="Doe"
                        value={lastName}
                        onChange={(e) => setLastName(e.target.value)}
                        data-testid="input-last-name"
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      placeholder="john@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      data-testid="input-email"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="company">Company</Label>
                    <Input
                      id="company"
                      placeholder="Acme Inc."
                      value={company}
                      onChange={(e) => setCompany(e.target.value)}
                      data-testid="input-company"
                    />
                  </div>
                  <Button
                    className="gap-2"
                    onClick={() => saveProfileMutation.mutate()}
                    disabled={saveProfileMutation.isPending}
                    data-testid="button-save-profile"
                  >
                    {saveProfileMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    Save Changes
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="appearance" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Theme</CardTitle>
              <CardDescription>
                Customize how the platform looks
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {theme === "dark" ? (
                    <Moon className="h-5 w-5 text-primary" />
                  ) : (
                    <Sun className="h-5 w-5 text-primary" />
                  )}
                  <div>
                    <p className="font-medium">Dark Mode</p>
                    <p className="text-sm text-muted-foreground">
                      Use dark theme for better visibility in low light
                    </p>
                  </div>
                </div>
                <Switch
                  checked={theme === "dark"}
                  onCheckedChange={(checked) => setTheme(checked ? "dark" : "light")}
                  data-testid="switch-dark-mode"
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="notifications" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Notification Preferences</CardTitle>
              <CardDescription>
                Choose what notifications you want to receive
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {[
                {
                  id: "email",
                  title: "Email Notifications",
                  description: "Receive notifications via email",
                },
                {
                  id: "queryComplete",
                  title: "Query Completion",
                  description: "Notify when long-running queries complete",
                },
                {
                  id: "segmentUpdates",
                  title: "Segment Updates",
                  description: "Notify when segment counts change significantly",
                },
                {
                  id: "exportStatus",
                  title: "Export Status",
                  description: "Notify when CRM exports complete or fail",
                },
              ].map((item) => (
                <div key={item.id} className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">{item.title}</p>
                    <p className="text-sm text-muted-foreground">{item.description}</p>
                  </div>
                  <Switch
                    checked={notifications[item.id as keyof typeof notifications]}
                    onCheckedChange={(checked) =>
                      setNotifications({ ...notifications, [item.id]: checked })
                    }
                    data-testid={`switch-${item.id}`}
                  />
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="security" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Password</CardTitle>
              <CardDescription>
                Change your password to keep your account secure
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="currentPassword">Current Password</Label>
                <Input id="currentPassword" type="password" data-testid="input-current-password" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="newPassword">New Password</Label>
                <Input id="newPassword" type="password" data-testid="input-new-password" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirm New Password</Label>
                <Input id="confirmPassword" type="password" data-testid="input-confirm-password" />
              </div>
              <Button className="gap-2" data-testid="button-update-password">
                <Key className="h-4 w-4" />
                Update Password
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
