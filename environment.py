import spade
import networkx as nx
import copy
from random import  randint
from bin_agent import BinAgent
from truck_agent import TruckAgent
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
import sys
from spade.message import Message
import asyncio
import time

class Environment():
    def __init__(self, width, height, grid): 
        self.width = width
        self.height = height
        self.grid = grid #[[0 for _ in range(width)] for _ in range(height)]  # Matriz vazia (0 = estrada)
        self.bins = {}  # lista (cooredenadas): agente 
        self.trucks = []  # lista com os agentes trucks
        self.central = (5,5)
        self.grid[5][5] = 2 # Colocar a central
        self.g = nx.Graph()
        self.convert_to_graph()
        self.start_time = time.time()
        # Estou a supor que ambos os agentes tem as posições onde se escontram neles definida

    @staticmethod
    def node_name_template(row, col):
        return "x=" + str(col) + " y=" + str(row)
    
    @staticmethod
    def get_pos_from_node_name(nodename):
        col_str, row_str = nodename.split(" ")
        col = int(col_str.split("=")[1])    # vem do x do nome
        row = int(row_str.split("=")[1])    # vem do y do nome
        return (row,col)

    def expand_aux(self, grid, row, col, dir_x, dir_y):
        n_col = col + dir_x
        n_row = row + dir_y
        if 0 <= n_col < len(grid[0]) and 0 <= n_row < len(grid):
            if grid[n_row][n_col] <= 2:
                self.g.add_node(self.node_name_template(n_row, n_col))
                if not self.g.has_edge(self.node_name_template(row, col), self.node_name_template(n_row, n_col)):
                    self.g.add_edge(self.node_name_template(row, col), self.node_name_template(n_row, n_col), weight=1)
        return

    def expand(self, grid, row, col, dirs):
        for direct in dirs:
            self.expand_aux(grid, row, col, direct[0], direct[1])
        return

    def convert_to_graph(self):
        grid = copy.deepcopy(self.grid)
        for row in range(len(grid)):
            for col in range(len(grid[0])):
                if grid[row][col] <= 2:         #any number below or equal to one represents the road or bins
                    grid[row][col] = -1
                    self.g.add_node(self.node_name_template(row, col))
                    self.expand(grid, row, col, [[1, 0], [-1, 0], [0, 1], [0, -1]])

    # Apenas guarda os nomes novos dos agentes
    async def add_bin(self, position):
        #Cria e adiciona um bin na posição especificada, garantindo que não há duplicados.
        if position in self.bins:
            print(f"Erro: Já existe um bin na posição {position}.")
        else:
            bin_name = "bin" + str(len(self.bins) + 1) + "@localhost"
            bin_agent = BinAgent(jid = bin_name, password = "password", environment = self, position = (position[1], position[0]))
            self.bins[position] = bin_agent
            self.grid[position[1]][position[0]] = 1  # (1 = caixote do lixo)
            print(f"[{bin_agent.name}] Bin criado e adicionado na posição {position}")
            await bin_agent.start(auto_register = True)   # Iniciar o agente

    # Retorna o bin na posição x
    def get_bin_at_position(self, position):
        """Retorna o bin na posição dada, ou None se não houver bin"""
        return self.bins.get((position[1], position[0]), None)
    
    async def add_truck(self, position):
        truck_name = "truck" + str(len(self.trucks) + 1) + "@localhost"
        truck_agent = TruckAgent(truck_name, "password", (position[1], position[0]), self)  #Criar o agente Truckd
        self.trucks.append(truck_agent)
        print(f"[{truck_agent.name}] Truck criado e adicionado em {position}")
        print(self.trucks)
        await truck_agent.start(auto_register = True)   # Iniciar o agente
        
    def get_all_trucks(self):
            """Retorna a lista de todos os trucks."""
            return self.trucks

    # new_position (row,col)
    def move_truck(self, truck, new_position):  # new_position vem como (y, x) = (row, col)
        # Verificar se a posição está dentro dos limites da matriz
        if 0 <= new_position[0] < self.height and 0 <= new_position[1] < self.width:
            truck.agent.position = (new_position[0], new_position[1])   # Atualizar o agente
            print(f"[{truck.agent.name}] Truck moved to ({new_position[1]},{new_position[0]}).")
            print(f"[{truck.agent.name}] Fuel = {truck.agent.fuel}")
        else:
            print(f"[{truck.agent.name}] New position out of bounds.")

    def get_nearby_bins(self, position):
        nearby_bins = []
        for bin in self.bins.values():
            if bin.current_waste >= bin.max_capacity*0.4:
                # Calcular distância (ou outro critério de proximidade)
                distance = abs(bin.position[0] - position[0]) + abs(bin.position[1] - position[1])
                if distance <= 15:  # Raio de exploração configurável
                    nearby_bins.append((bin, distance))
        sorted_bins = sorted(nearby_bins, key=lambda x: x[1])
        # Retorna apenas os bins, descartando as distâncias
        return [bin for bin, _ in sorted_bins]

    # postion(x,y)
    async def add_roadBlock(self, position):
        self.grid[position[1]][position[0]]=9
        node_name=self.node_name_template(position[1],position[0])
        edges=list(self.g.edges(node_name))
        for edge_name in edges:
            # removes the edge that connects the nodes in edge_name (*edge_name serves to unpack the tuple (node1_name, node2,_name))
            self.g.remove_edge(*edge_name)
        print("ROAD BLOCK CRIADO")
        self.sendEnvironmentUpdate()

    # position(row,col)
    async def remove_roadBlock(self, position):
        self.grid[position[1]][position[0]]=0
        node_name=self.node_name_template(position[1],position[0])
        adjacent_nodes=[]
        # get valid vertical adjacent nodes
        for i in [-1,1]:
            if(0<=position[1]+i<self.height):
                adjacent_nodes.append(self.node_name_template(position[1]+i,position[0]))
        # get valid horizontal adjacent nodes 
        for i in [-1,1]:
            if(0<=position[0]+i<self.width):
                adjacent_nodes.append(self.node_name_template(position[1],position[0]+i))
        # add all the edges that connect the roadblock node to it's adjacents 
        for adjacent_node in adjacent_nodes:
            self.g.add_edge(node_name, adjacent_node, weight=1)
        self.sendEnvironmentUpdate()

    # level 0 resets al traffic
    async def set_traffic(self, level):
        #dictate the percentage of edeges of the graph that are going to be affected and by how much
        match level:
            case 0:
                edges=list(self.g.edges())
                for edge_name in edges:
                    self.g.edges[edge_name]['weight'] = 1
                return
            case 1:
                percentage=0.3
                multiplier=1.5
            case 2:
                percentage=0.3
                multiplier=2
            case 3:
                percentage=0.5
                multiplier=2
            case 4:
                percentage=0.6
                multiplier=2.5
            case 5:
                percentage=0.8
                multiplier=3
            case _:
                print("Invalid level of traffic, no traffic applied")
                return
            
        edges=list(self.g.edges)
        n_edges=int(len(edges)*percentage)

        for _ in range(n_edges):
            idx=randint(0,len(edges)-1)
            edge_name=edges[idx]
            current_weight= self.g.edges[edge_name].get('weight')
            self.g.edges[edge_name]['weight']= int(current_weight*multiplier)
        
        self.sendEnvironmentUpdate()

    def sendEnvironmentUpdate(self):
        for truck in self.trucks:
            truck.changes = True

    # returns the amount of time since the initialization of the environment in seconds
    def timer (self):
        return int(time.time()-self.start_time)

    def break_truck(self, last_call):
        cur_time = self.timer()
        # 5 é o intervalo e tempo necessário para um truck ficar avariado 
        if (cur_time > (90 + last_call)) and len(self.trucks) > 0 and randint(0,1) == 1:
            truck = self.trucks[randint(0, len(self.trucks) - 1)]
            truck.is_broken = True
            return self.timer()
        return last_call

    async def start_system(self):
        for bin in self.bins.values():
            bin.add_behaviour(bin.WasteAccumulationBehaviour(period=bin.accumulation_period))
        for truck in self.trucks:
            truck.add_behaviour(truck.ExploreEnvironmentBehaviour())

    def update_display(self):
            # Collect all traffic-affected edges
        traffic_edges = [
        (self.get_pos_from_node_name(edge[0]), self.get_pos_from_node_name(edge[1]))
        for edge in self.g.edges
        if self.g.edges[edge].get('weight', 1) > 1
        ]
        return self.grid, self.trucks, self.bins, traffic_edges
