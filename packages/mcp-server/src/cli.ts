#!/usr/bin/env node
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createPricingMcpServer } from "./server.js";

const server = createPricingMcpServer();
await server.connect(new StdioServerTransport());
