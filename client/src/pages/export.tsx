import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { apiRequest, queryClient } from "@/lib/queryClient";
import {
  Send,
  Check,
  X,
  Clock,
  AlertCircle,
  Users,
  Tag,
  Calendar,
  ExternalLink,
  RefreshCw,
  ArrowRight,
} from "lucide-react";
import type { Segment, GhlExport } from "@shared/schema";

export default function Export() {
  const [selectedSegmentId, setSelectedSegmentId] = useState<number | null>(null);
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);
  const [locationId, setLocationId] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");

  const { data: segments } = useQuery<Segment[]>({
    queryKey: ["/api/segments"],
  });

  const { data: exports, isLoading: isLoadingExports } = useQuery<GhlExport[]>({
    queryKey: ["/api/exports"],
  });

  const exportMutation = useMutation({
    mutationFn: async () => {
      const response = await apiRequest("POST", "/api/exports", {
        segmentId: selectedSegmentId,
        ghlLocationId: locationId,
        ghlTags: tags,
      });
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/exports"] });
      setIsExportDialogOpen(false);
      setSelectedSegmentId(null);
      setLocationId("");
      setTags([]);
    },
  });

  const handleAddTag = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && tagInput.trim()) {
      e.preventDefault();
      if (!tags.includes(tagInput.trim())) {
        setTags([...tags, tagInput.trim()]);
      }
      setTagInput("");
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter((tag) => tag !== tagToRemove));
  };

  const selectedSegment = segments?.find((s) => s.id === selectedSegmentId);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <Check className="h-4 w-4 text-green-500" />;
      case "failed":
        return <X className="h-4 w-4 text-red-500" />;
      case "pending":
        return <Clock className="h-4 w-4 text-amber-500" />;
      default:
        return <Clock className="h-4 w-4 text-muted-foreground" />;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return <Badge variant="default" className="bg-green-500">Completed</Badge>;
      case "failed":
        return <Badge variant="destructive">Failed</Badge>;
      case "pending":
        return <Badge variant="secondary">Pending</Badge>;
      case "processing":
        return <Badge variant="default">Processing</Badge>;
      default:
        return <Badge variant="secondary">{status}</Badge>;
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Send className="h-6 w-6 text-primary" />
            Export to CRM
          </h1>
          <p className="text-muted-foreground mt-1">
            Send customer segments to GoHighLevel for marketing campaigns
          </p>
        </div>
        <Button
          onClick={() => setIsExportDialogOpen(true)}
          className="gap-2"
          data-testid="button-new-export"
        >
          <Send className="h-4 w-4" />
          New Export
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <RefreshCw className="h-5 w-5 text-primary" />
              Export History
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoadingExports ? (
              <div className="space-y-4">
                {[...Array(3)].map((_, i) => (
                  <Skeleton key={i} className="h-20 w-full" />
                ))}
              </div>
            ) : !exports || exports.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center mb-4">
                  <Send className="h-8 w-8 text-muted-foreground" />
                </div>
                <h3 className="text-lg font-semibold mb-2">No Exports Yet</h3>
                <p className="text-sm text-muted-foreground max-w-md mb-6">
                  Export your customer segments to GoHighLevel to start
                  running targeted marketing campaigns.
                </p>
                <Button onClick={() => setIsExportDialogOpen(true)} className="gap-2">
                  <Send className="h-4 w-4" />
                  Create First Export
                </Button>
              </div>
            ) : (
              <div className="space-y-4">
                {exports.map((exp) => (
                  <div
                    key={exp.id}
                    className="flex items-center justify-between p-4 rounded-lg bg-muted/50 hover-elevate transition-colors"
                    data-testid={`export-item-${exp.id}`}
                  >
                    <div className="flex items-center gap-4">
                      {getStatusIcon(exp.status || "pending")}
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">
                            Segment #{exp.segmentId}
                          </span>
                          {getStatusBadge(exp.status || "pending")}
                        </div>
                        <div className="flex items-center gap-4 mt-1 text-sm text-muted-foreground">
                          <span className="flex items-center gap-1">
                            <Users className="h-3 w-3" />
                            {exp.contactCount.toLocaleString()} contacts
                          </span>
                          {exp.ghlTags && exp.ghlTags.length > 0 && (
                            <span className="flex items-center gap-1">
                              <Tag className="h-3 w-3" />
                              {exp.ghlTags.length} tags
                            </span>
                          )}
                          <span className="flex items-center gap-1">
                            <Calendar className="h-3 w-3" />
                            {new Date(exp.createdAt).toLocaleDateString()}
                          </span>
                        </div>
                        {exp.errorMessage && (
                          <p className="text-sm text-destructive mt-1 flex items-center gap-1">
                            <AlertCircle className="h-3 w-3" />
                            {exp.errorMessage}
                          </p>
                        )}
                      </div>
                    </div>
                    <Button variant="ghost" size="sm" className="gap-2">
                      View Details
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ExternalLink className="h-5 w-5 text-primary" />
              GoHighLevel Connection
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3 p-4 rounded-lg bg-muted/50">
              <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                <Check className="h-5 w-5 text-green-500" />
              </div>
              <div>
                <p className="font-medium text-sm">Connected</p>
                <p className="text-xs text-muted-foreground">
                  API connection active
                </p>
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Location ID</span>
                <span className="font-mono text-xs">Configure in settings</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Last Sync</span>
                <span>Just now</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Total Exported</span>
                <span>{exports?.reduce((acc, e) => acc + e.contactCount, 0)?.toLocaleString() || 0}</span>
              </div>
            </div>
            <Button variant="outline" className="w-full gap-2" data-testid="button-configure-ghl">
              Configure Connection
            </Button>
          </CardContent>
        </Card>
      </div>

      <Dialog open={isExportDialogOpen} onOpenChange={setIsExportDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Export Segment to GoHighLevel</DialogTitle>
            <DialogDescription>
              Select a segment and configure how contacts should be imported into GoHighLevel.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Select Segment</Label>
              <Select
                value={selectedSegmentId?.toString() || ""}
                onValueChange={(v) => setSelectedSegmentId(parseInt(v))}
              >
                <SelectTrigger data-testid="select-export-segment">
                  <SelectValue placeholder="Choose a segment to export" />
                </SelectTrigger>
                <SelectContent>
                  {segments?.map((segment) => (
                    <SelectItem key={segment.id} value={segment.id.toString()}>
                      <div className="flex items-center gap-2">
                        {segment.name}
                        <Badge variant="secondary" className="ml-2">
                          {segment.contactCount?.toLocaleString() || 0}
                        </Badge>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {selectedSegment && (
              <div className="p-3 rounded-lg bg-muted/50">
                <p className="text-sm font-medium">{selectedSegment.name}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {selectedSegment.contactCount?.toLocaleString() || 0} contacts will be exported
                </p>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="locationId">GoHighLevel Location ID</Label>
              <Input
                id="locationId"
                placeholder="Enter your GHL location ID"
                value={locationId}
                onChange={(e) => setLocationId(e.target.value)}
                data-testid="input-ghl-location"
              />
            </div>

            <div className="space-y-2">
              <Label>Tags (Press Enter to add)</Label>
              <Input
                placeholder="Add tags for these contacts..."
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={handleAddTag}
                data-testid="input-ghl-tags"
              />
              {tags.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2">
                  {tags.map((tag) => (
                    <Badge key={tag} variant="secondary" className="gap-1">
                      {tag}
                      <button
                        onClick={() => handleRemoveTag(tag)}
                        className="ml-1 hover:text-destructive"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsExportDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => exportMutation.mutate()}
              disabled={!selectedSegmentId || !locationId || exportMutation.isPending}
              className="gap-2"
              data-testid="button-confirm-export"
            >
              {exportMutation.isPending ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Exporting...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  Export Contacts
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
