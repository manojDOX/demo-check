import { Link, useLocation } from "wouter";
import {
  Database,
  BarChart3,
  Users,
  Sparkles,
  Settings,
  Layers,
  Send,
  MessageSquare,
  Home,
  ChevronRight,
  Building2,
} from "lucide-react";
import xiomaraLogo from "@assets/logo_xiomara_2_1769277766982.png";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useRole } from "@/hooks/use-role";

const viewerAllowedUrls = ["/", "/query", "/analytics"];

const dataWhispererItems = [
  {
    title: "Dashboard",
    url: "/",
    icon: Home,
    viewerAccess: true,
  },
  {
    title: "Ask Your Data",
    url: "/query",
    icon: MessageSquare,
    viewerAccess: true,
  },
  {
    title: "KPI Analytics",
    url: "/analytics",
    icon: BarChart3,
    viewerAccess: true,
  },
  {
    title: "Segmentation",
    url: "/segments",
    icon: Users,
    viewerAccess: false,
  },
  {
    title: "Export to CRM",
    url: "/export",
    icon: Send,
    viewerAccess: false,
  },
];

const dynamicPersonaItems = [
  {
    title: "Page Builder",
    url: "/dynamic-persona",
    icon: Layers,
    comingSoon: false,
  },
  {
    title: "Personalization",
    url: "/persona/personalization",
    icon: Sparkles,
    comingSoon: true,
  },
];

const settingsItems = [
  {
    title: "Connections",
    url: "/settings/connections",
    icon: Database,
  },
  {
    title: "Business Profile",
    url: "/settings/business-profile",
    icon: Building2,
  },
  {
    title: "Settings",
    url: "/settings",
    icon: Settings,
  },
];

export function AppSidebar() {
  const [location] = useLocation();
  const { isAdmin, isViewer } = useRole();
  const { isMobile, setOpenMobile } = useSidebar();

  const closeMobileSidebar = () => {
    if (isMobile) setOpenMobile(false);
  };

  const visibleDataItems = isViewer
    ? dataWhispererItems.filter(item => item.viewerAccess)
    : dataWhispererItems;

  return (
    <Sidebar>
      <SidebarHeader className="border-b border-sidebar-border px-4 py-4">
        <Link href="/" className="flex items-center">
          <img src={xiomaraLogo} alt="Xiomara" className="h-8" />
        </Link>
      </SidebarHeader>

      <SidebarContent className="custom-scrollbar">
        <SidebarGroup>
          <SidebarGroupLabel className="flex items-center gap-2 px-4 text-xs font-medium uppercase tracking-wider text-sidebar-foreground/50">
            <Database className="h-3.5 w-3.5" />
            Data Whisperer
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {visibleDataItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    isActive={location === item.url}
                    className={cn(
                      "transition-colors",
                      location === item.url && "bg-sidebar-accent"
                    )}
                  >
                    <Link href={item.url} onClick={closeMobileSidebar} data-testid={`nav-${item.title.toLowerCase().replace(/\s+/g, '-')}`}>
                      <item.icon className="h-4 w-4" />
                      <span>{item.title}</span>
                      {location === item.url && (
                        <ChevronRight className="ml-auto h-4 w-4 text-sidebar-foreground/50" />
                      )}
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {isAdmin && (
          <SidebarGroup>
            <SidebarGroupLabel className="flex items-center gap-2 px-4 text-xs font-medium uppercase tracking-wider text-sidebar-foreground/50">
              <Sparkles className="h-3.5 w-3.5" />
              Dynamic Persona
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {dynamicPersonaItems.map((item) => (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      isActive={location === item.url}
                      disabled={item.comingSoon}
                      className={cn(
                        "transition-colors",
                        item.comingSoon && "opacity-50 cursor-not-allowed"
                      )}
                    >
                      <Link href={item.comingSoon ? "#" : item.url} onClick={closeMobileSidebar} data-testid={`nav-${item.title.toLowerCase().replace(/\s+/g, '-')}`}>
                        <item.icon className="h-4 w-4" />
                        <span>{item.title}</span>
                        {item.comingSoon && (
                          <Badge variant="secondary" className="ml-auto text-[10px] px-1.5 py-0">
                            Soon
                          </Badge>
                        )}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {isAdmin && settingsItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    isActive={location === item.url || location.startsWith(item.url + "/")}
                    className="transition-colors"
                  >
                    <Link href={item.url} onClick={closeMobileSidebar} data-testid={`nav-${item.title.toLowerCase().replace(/\s+/g, '-')}`}>
                      <item.icon className="h-4 w-4" />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
              {isViewer && (
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={location === "/settings"}
                    className="transition-colors"
                  >
                    <Link href="/settings" onClick={closeMobileSidebar} data-testid="nav-settings">
                      <Settings className="h-4 w-4" />
                      <span>Settings</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarFooter>
    </Sidebar>
  );
}
