# Multi-Agent-Autonomous-Waste-Collection-System
Designed and implemented a decentralized waste collection system using Multi-Agent Systems (MAS) with SPADE


This repository contains the implementation of a decentralized waste collection system using Multi-Agent Systems (MAS). The system simulates autonomous garbage trucks collaborating to efficiently collect waste from a dynamically changing urban environment.

# Project Overview
In large urban areas, efficient waste management is a challenge due to variable waste production and unpredictable traffic conditions. This project addresses the problem by deploying autonomous agents (garbage trucks and bins) that operate in a decentralized manner. Each agent collaborates with others to optimize waste collection, resource usage, and system performance.

# Objectives
The main goals of this project include:

Developing autonomous garbage truck agents capable of dynamic route planning and task allocation.

Creating waste bin agents that monitor fill levels and request collection when necessary.

Ensuring decentralized decision-making for efficient resource usage and city-wide coverage.

Handling dynamic environments with changing traffic conditions and roadblocks.

Implementing fault-tolerant behavior to ensure uninterrupted waste collection.

# Features

Agents

### Truck Agents:

Detect and respond to waste bin fill levels.

Optimize routes considering fuel/battery levels and current capacity ( using Dijsktras algorithm)

Collaborate with other agents to avoid redundant collections.

### Bin Agents:

Monitor fill levels and report to nearby truck agents.

Trigger collection requests upon reaching a specified threshold.

Decentralized Decision-Making : Truck agents independently decide their actions based on local information and inter-agent communication.

Use of task allocation protocols like the Contract Net Protocol to enable collaboration and efficient task distribution.


_________________________________________________________________________________________________________________________________________________________

###### Dynamic Environment:

Simulation includes traffic variations, roadblocks, and fluctuating waste production levels.

Agents adapt routes in real time to changing conditions.

###### Resource Management:

Efficient planning to minimize fuel consumption and maximize waste collection.

Trucks return to a central depot to unload or recharge as needed.

Fault Tolerance

Redistribution of tasks among agents if one or more truck agents fail.
