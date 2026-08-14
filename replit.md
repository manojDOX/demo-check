# Marketing Intelligence Platform

## Overview
A unified marketing intelligence SaaS platform with two main modules:
1. **Data Whisperer** - AI-powered BigQuery analytics with natural language queries, KPI dashboards (9 retail metrics), customer segmentation, and GoHighLevel CRM export
2. **Dynamic Persona** - AI-powered personalized website builder (coming soon)

## Tech Stack
- **Frontend**: React 18 + TypeScript + Vite + TailwindCSS + shadcn/ui
- **Backend**: Express.js + TypeScript
- **Database**: PostgreSQL (Neon) + Drizzle ORM
- **AI**: OpenAI via Replit AI Integrations (GPT-4o-mini)
- **Charts**: Recharts

## Project Structure
```
client/
├── src/
│   ├── components/     # Reusable UI components
│   │   ├── app-sidebar.tsx       # Main navigation sidebar
│   │   ├── client-selector.tsx   # Client dropdown
│   │   ├── kpi-card.tsx          # KPI metric card
│   │   ├── query-input.tsx       # Natural language query input
│   │   ├── query-result.tsx      # Query results with charts
│   │   └── theme-toggle.tsx      # Dark/light mode toggle
│   ├── pages/          # Application pages
│   │   ├── dashboard.tsx         # Main dashboard with KPIs
│   │   ├── query.tsx             # Natural language query interface
│   │   ├── analytics.tsx         # Detailed KPI analytics
│   │   ├── segments.tsx          # Customer segmentation
│   │   ├── export.tsx            # GoHighLevel export
│   │   ├── connections.tsx       # BigQuery connections
│   │   ├── settings.tsx          # User settings
│   │   └── coming-soon.tsx       # Dynamic Persona placeholder
│   └── lib/            # Utilities and providers
server/
├── routes.ts           # API endpoints
├── storage.ts          # Database operations
└── db.ts               # Database connection
shared/
├── schema.ts           # Drizzle database schema
└── models/             # Additional models
```

## Key Features

### Data Whisperer Module
- **Natural Language Queries**: Ask questions in plain English, get SQL and results
- **Segment Drill-Down**: Iteratively sub-query result sets - click "Drill into Segment" to chain SQL queries via subquery wrapping (works at any depth), with breadcrumb navigation to track and navigate the drill-down chain
- **AI Recommendations**: Detects recommendation intent (Spanish/English) and provides actionable marketing insights based on business context
- **Business Profiles**: Per-client business description, target audience, and additional info that feeds into AI recommendations
- **Product Catalog**: Per-client product catalog (name, description, benefits, cost, price, category) used by AI for specific product-aware recommendations
- **9 Retail KPIs**: Total Sales, Orders, AOV, Recurrence Rate, New/Returning Customers, Cart Abandonment, LTV, Return Rate
- **Customer Segmentation**: AI-generated and manual segments
- **GoHighLevel Integration**: Direct CRM sync - send queried customer segments as contacts (name, email, phone) with auto field mapping, rate-limited API calls, and sync results summary. Configure API Key and Location ID in Settings > Integrations.

### Team Collaboration
- **Invite-only collaborators**: Account admins can invite team members by email from Settings > Team
- **Client-specific access**: Each collaborator is assigned specific clients they can view
- **Role-based sidebar**: Viewers see only Dashboard, Ask your Data, and KPI Analytics
- **Auto-linking**: When an invited user logs in with the matching email, their account is automatically linked
- **Access control**: Admin-only pages (Segments, Export, Connections, Dynamic Persona) are protected via route guards

### Design System
- Professional dark theme with blue/cyan accent colors
- Custom CSS utilities: `gradient-text`, `glass-effect`, `shimmer`, `pulse-glow`
- Responsive design with custom scrollbars
- Built on shadcn/ui components

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/clients` | GET, POST | Manage retail clients |
| `/api/connections` | GET, POST, DELETE | BigQuery connections |
| `/api/connections/:id/test` | POST | Test connection |
| `/api/segments` | GET, POST | Customer segments |
| `/api/segments/generate` | POST | AI-generate segments |
| `/api/queries` | GET, POST | Natural language queries |
| `/api/kpis` | GET | KPI snapshots |
| `/api/exports` | GET, POST | GoHighLevel exports |
| `/api/ghl/settings` | GET, PUT | GHL API key & location config |
| `/api/ghl/send-contacts` | POST | Send contacts to GHL CRM |
| `/api/auth/role` | GET | Get current user role (admin/viewer) |
| `/api/team` | GET, POST | List/invite team collaborators |
| `/api/team/:id` | PATCH, DELETE | Update/remove collaborators |
| `/api/business-profile/:clientId` | GET, PUT | Business profile per client |
| `/api/product-catalog/:clientId` | GET, POST | Product catalog per client |
| `/api/product-catalog/:clientId/:id` | PATCH, DELETE | Update/remove products |

## Database Schema
- `users` - Platform users
- `bigquery_connections` - BigQuery credentials
- `clients` - Retail clients
- `business_profiles` - Per-client business context for AI recommendations
- `product_catalog` - Per-client product catalog for AI recommendations
- `segments` - Customer segments
- `queries` - Query history
- `kpi_snapshots` - Pre-computed daily KPIs
- `ghl_exports` - GoHighLevel export history
- `team_members` - Collaborator invitations and access
- `team_member_clients` - Client-specific access per collaborator
- `page_designs` - Dynamic Persona pages (future)
- `personalization_zones` - Page personalization (future)
- `anonymous_visitors` - Visitor tracking (future)
- `navigation_events` - Behavioral events (future)
- `content_library` - Reusable content (future)

## Running the Project
```bash
npm run dev      # Start development server
npm run db:push  # Push schema to database
```

## User Preferences
- Default theme: Dark mode
- Design: Professional, minimal, no emojis
- Architecture: Monorepo with unified admin shell
