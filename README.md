# BGP-LS Topology Viewer

A full-stack application for visualizing BGP-LS (Border Gateway Protocol - Link State) network topology from OpenDaylight (ODL) controller.

## Architecture

```
┌─────────────────────────────────┐
│  React Frontend (Port 5173)     │
│  - Cytoscape.js visualization   │
│  - Interactive topology display │
└────────────┬────────────────────┘
             │ REST API
┌────────────▼────────────────────┐
│  Spring Boot Backend (Port 8080)│
│  - ODL REST client              │
│  - Topology data processing     │
└────────────┬────────────────────┘
             │ REST API
┌────────────▼────────────────────┐
│  OpenDaylight Controller        │
│  - BGP-LS plugin                │
│  - Network topology data        │
└─────────────────────────────────┘
```

## Features

- **Real-time topology visualization** using Cytoscape.js
- **Interactive graph controls** - zoom, pan, fit, center
- **Node and link details** display
- **Auto-refresh capability** for live topology updates
- **Statistics panel** showing node/link counts and metrics
- **Responsive design** for different screen sizes
- **Spring Boot backend** with reactive WebClient
- **CORS-enabled** for local development

## Prerequisites

- **Java 17** or higher
- **Maven 3.6+**
- **Node.js 18+** and npm
- **OpenDaylight Controller** with BGP-LS plugin (running on port 8181)

## Project Structure

```
.
├── backend/                 # Spring Boot application
│   ├── src/main/java/
│   │   └── com/odl/bgpls/topology/
│   │       ├── config/      # Configuration classes
│   │       ├── controller/  # REST controllers
│   │       ├── model/       # Data models
│   │       └── service/     # Business logic
│   └── pom.xml
├── frontend/                # React application
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── services/        # API client
│   │   ├── types/           # TypeScript types
│   │   └── styles/          # CSS files
│   └── package.json
└── README.md
```

## Quick Start

### 1. Start OpenDaylight Controller

Ensure your ODL controller is running with BGP-LS topology data:

```bash
# Default ODL configuration
URL: http://localhost:8181
Username: admin
Password: admin
```

### 2. Start Backend

```bash
cd backend
mvn clean install
mvn spring-boot:run
```

The backend will start on **http://localhost:8080**

### 3. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend will start on **http://localhost:5173**

### 4. Access the Application

Open your browser and navigate to **http://localhost:5173**

## Configuration

### Backend Configuration

Edit `backend/src/main/resources/application.properties`:

```properties
# OpenDaylight Configuration
odl.base-url=http://localhost:8181
odl.username=admin
odl.password=admin
odl.topology-id=example-linkstate-topology

# Server Configuration
server.port=8080
```

### Frontend Configuration

Edit `frontend/src/services/topologyService.ts` to change the backend URL:

```typescript
baseURL: 'http://localhost:8080/api'
```

## API Endpoints

### Backend REST API

- `GET /api/topology` - Get current BGP-LS topology
- `GET /api/topology/list` - Get list of available topologies
- `GET /api/topology/health` - Health check endpoint

### OpenDaylight REST API

The backend connects to:
- `GET /restconf/data/network-topology:network-topology`
- `GET /restconf/data/network-topology:network-topology/topology={topology-id}`

## Usage

### Viewing Topology

1. The application automatically fetches topology data on load
2. Use **Fit** button to fit the entire topology in view
3. Use **Center** button to center the topology
4. Use **Reset** button to reset zoom and pan
5. Click on nodes or links to see details in the console

### Auto-Refresh

Enable **Auto Refresh** checkbox to automatically update topology every 10 seconds.

### Manual Refresh

Click the **Refresh** button to manually fetch the latest topology data.

## Development

### Backend Development

```bash
cd backend

# Run tests
mvn test

# Build JAR
mvn clean package

# Run with specific profile
mvn spring-boot:run -Dspring-boot.run.profiles=dev
```

### Frontend Development

```bash
cd frontend

# Run development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Run linter
npm run lint
```

## Troubleshooting

### Backend Cannot Connect to ODL

1. Verify ODL is running: `curl http://localhost:8181/restconf/data/network-topology:network-topology`
2. Check credentials in `application.properties`
3. Verify BGP-LS plugin is installed in ODL

### Frontend Cannot Connect to Backend

1. Verify backend is running on port 8080
2. Check CORS configuration in `CorsConfig.java`
3. Open browser console for detailed error messages

### Empty Topology Display

1. Verify BGP-LS topology exists in ODL
2. Check topology-id in backend configuration
3. Use ODL REST API directly to verify data exists

## Technology Stack

### Backend
- Spring Boot 3.2.0
- Spring WebFlux (Reactive HTTP client)
- Java 17
- Maven
- Lombok

### Frontend
- React 19
- TypeScript
- Vite
- Cytoscape.js 3.33
- Axios

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is open-source and available under the MIT License.

## Support

For issues and questions:
- Check the troubleshooting section
- Review ODL BGP-LS documentation
- Open an issue on the project repository

## Acknowledgments

- OpenDaylight community for BGP-LS implementation
- Cytoscape.js for graph visualization
- Spring Boot and React communities
