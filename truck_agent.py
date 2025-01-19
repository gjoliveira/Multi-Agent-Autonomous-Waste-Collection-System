from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
import spade
import asyncio
import networkx as nx
import ast

class TruckAgent(Agent):
    def __init__(self, jid, password, position, environment):
        super().__init__(jid, password)
        self.environment = environment
        self.load = 0   # Current capacity
        self.max_load = 400 # Max quantity of trash it can carry
        self.fuel = 100   # Current fuel 
        self.max_fuel = 100 # Max quantity of fuel it can have
        self.position = position # we always consider position to be (row,col)
        self.is_busy = False   # True if truck is busy going to a bin, False if it has nothing to do
        self.emergency = False
        self.exploration_bin = None  # Target bin during exploration (saves bin)
        self.current_path = None
        self.where = None
        self.not_accessible_bins = []   # Bins claimed by other trucks
        self.no_path = []   # Não há caminho para estes bins
        self.changes = False
        self.is_broken = False
        self.collected_waste = 0    # Guarda o total de lixo recolhido
        self.total_fuel = 0     # Guarda o valor total de fuel gasto
        self.total_distance = 0    # Guarda o valor total de distancia percorrida
        self.collab = 0  # Guarda o número de vezes que colaboraram / houve allocations

    class ReceiveCFPBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=1)
            if msg and msg.metadata.get("performative") == "cfp":
                row, col = map(int, msg.body.split(","))
                bin_location = (row, col)
                if self.agent.is_busy or self.agent.is_broken:
                    await self.decline_proposal(msg.sender)
                # check if it possible to get to the bin
                elif not nx.has_path(self.agent.environment.g,
                                 self.agent.environment.node_name_template(self.agent.position[0],self.agent.position[1]),
                                 self.agent.environment.node_name_template(bin_location[0],bin_location[1])):
                    if bin_location not in self.agent.no_path:
                        self.agent.no_path.append(bin_location)
                        self.agent.not_accessible_bins.append(bin_location)
                    await self.decline_proposal(msg.sender)
                else:
                    is_possible = self.agent.get_cost(self.agent.position, bin_location) + self.agent.get_cost(bin_location, self.agent.environment.central)
                    if is_possible < self.agent.fuel and not self.agent.is_busy:
                        await self.prepare_proposal(bin_location, msg.sender)
                    else:
                        await self.decline_proposal(msg.sender)
        
        async def decline_proposal(self, bin_jid):
            decline_msg = Message(to = str(bin_jid))
            decline_msg.set_metadata("performative", "decline")
            decline_msg.body = "Truck is busy"
            await self.send(decline_msg)
            print(f"[{self.agent.name}] Truck rejected the request from {bin_jid} (busy).")
    
        async def prepare_proposal(self, bin_position, bin_jid):
            estimated_cost, best_route = self.agent.get_shortest_path(bin_position)
            proposal = Message(to = str(bin_jid))
            proposal.set_metadata("performative", "propose")
            proposal.body = f"{best_route};{estimated_cost};{self.agent.max_load - self.agent.load};{self.agent.fuel}"
            await self.send(proposal)
            print(f"[{self.agent.name}] Truck sent proposal to CFP of bin at ({bin_position[1]},{bin_position[0]}) with cost {estimated_cost}.")

    # returns an tuple (shortest_path_len, shortest_path)
    # newpostion should be (row,col) in other words (y,x)
    def get_shortest_path(self, new_position):

        source_node = self.environment.node_name_template(self.position[0], self.position[1])
        target_node = self.environment.node_name_template(new_position[0], new_position[1])

        # path is calculated with the weight attribute of the edges, it includes the source and the target
        path = nx.shortest_path(self.environment.g, source=source_node, target=target_node, method='dijkstra',weight='weight')
        cost = nx.shortest_path_length(self.environment.g, source=source_node, target=target_node, method='dijkstra',weight='weight')
        return (cost, path)
    
    # returns the cost from one point to the other
    def get_cost(self, begin, end):
        source_node = self.environment.node_name_template(begin[0], begin[1])
        target_node = self.environment.node_name_template(end[0], end[1])
        cost = nx.shortest_path_length(self.environment.g, source=source_node, target=target_node, method='dijkstra',weight='weight')
        return cost

    class ReceiveAcceptanceBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout = 1)
            if msg and msg.metadata.get("performative") == "accept":
                if not self.agent.is_broken and not self.agent.emergency and not self.agent.is_busy:
                    # If an accept message is received, cancel the exploration
                    if self.agent.exploration_bin != None:
                        await self.send_release_message(self.agent.exploration_bin.position)
                    self.agent.is_busy = True
                    self.agent.current_path = ast.literal_eval(msg.body)
                    bin_pos = self.agent.environment.get_pos_from_node_name(self.agent.current_path[-1])
                    bin = self.agent.environment.get_bin_at_position(bin_pos)
                    self.agent.exploration_bin = bin
                    self.agent.where = "bin"
                    print(f"[{self.agent.name}] Received accept message of CFP. Moving to assigned bin.")
                    #await self.send_claim_message(bin, self.agent.get_cost(self.agent.position, bin_pos))
                else:
                    path = ast.literal_eval(msg.body)
                    pos = self.agent.environment.get_pos_from_node_name(path[-1])
                    await self.warn_bin(pos)
                    await self.alocate_others_trucks(pos)

        async def warn_bin(self, pos):
            warn_msg = Message()
            warn_msg.set_metadata("performative", "problem")
            bin = self.agent.environment.get_bin_at_position(pos)
            warn_msg.to = str(bin.jid)
            await self.send(warn_msg)
            print(f"[{self.agent.name}] Can't go to bin ({bin.position[1]},{bin.position[0]}). Bin warned.")

        async def alocate_others_trucks(self, bin_position):
            print("Entrou em alocate")
            allocate_task_msg = Message()
            allocate_task_msg.set_metadata("performative", "allocate-task")
            allocate_task_msg.body=f"{bin_position[0]},{bin_position[1]}"
            for truck in self.agent.environment.trucks:
                if(truck.jid != self.agent.jid):
                    allocate_task_msg.to = str(truck.jid)
                    await self.send(allocate_task_msg)
                    print(f"[{self.agent.name}] Asking [{allocate_task_msg.to}] to go to the bin ({bin_position[1]},{bin_position[0]}).")
        
        # Send claim message to all trucks
        async def send_claim_message(self, bin, cost):
            claim_msg = Message()
            claim_msg.set_metadata("performative", "claim-bin")
            claim_msg.body = f"{bin.position[0]},{bin.position[1]},{cost},{self.agent.fuel},{self.agent.max_load - self.agent.load}"
            for truck in self.agent.environment.trucks:
                if truck.jid != self.agent.jid:
                    claim_msg.to = str(truck.jid)
                    await self.send(claim_msg)
                    print(f"[{self.agent.name}] Sent claim message for bin at ({bin.position[1]},{bin.position[0]}) to {truck.jid} due to CFP acceptance.")

        # Send release message to all trucks
        async def send_release_message(self, bin_position):
            release_msg = Message()
            release_msg.set_metadata("performative", "release-bin")
            release_msg.body = f"{bin_position[0]},{bin_position[1]}"
            for truck in self.agent.environment.trucks:
                if truck.jid != self.agent.jid:
                    release_msg.to = str(truck.jid)
                    await self.send(release_msg)
            print(f"[{self.agent.name}] Sent release message for bin at ({bin_position[1]},{bin_position[0]}).")

    class ExploreEnvironmentBehaviour(CyclicBehaviour):
        async def run(self):
            if not self.agent.is_busy and not self.agent.emergency and not self.agent.is_broken and self.agent.exploration_bin == None:
                self.agent.current_path = None
                nearby_bins = self.agent.environment.get_nearby_bins(self.agent.position)
                for bin in nearby_bins:
                    if bin.position not in self.agent.not_accessible_bins and not self.agent.is_busy and not self.agent.is_broken:
                        try: 
                            cost, path = self.agent.get_shortest_path(bin.position)
                            self.agent.exploration_bin = bin
                            self.agent.where = 'bin'
                            if (not self.agent.is_busy and not self.agent.is_broken):
                                await self.send_claim_message(bin, cost)
                                print(f"[{self.agent.name}] Waiting for responses after claiming bin at ({bin.position[1]},{bin.position[0]}) for EXPLORATION.")
                                await asyncio.sleep(2)  # Espera por respostas
                            if not self.agent.is_busy and not self.agent.emergency and not self.agent.is_broken and bin.position not in self.agent.not_accessible_bins:
                                print(f"[{self.agent.name}] Selected bin at ({bin.position[1]},{bin.position[0]}) for exploration.")
                                self.agent.current_path = path
                                break
                            else:
                                print(f"[{self.agent.name}] Bin at ({bin.position[1]},{bin.position[0]}) was declined for exploration.")
                                if not self.agent.is_busy and not self.agent.emergency:
                                    self.agent.exploration_bin = None
                                    self.agent.where = None
                                    self.agent.current_path = None
                                break
                        except Exception as e:
                            print(f"[{self.agent}] Não exite caminho para o bin ({bin.position[1]},{bin.position[0]})")
                            self.agent.exploration_bin = None
                            self.agent.where = None
                            self.agent.current_path = None
                            self.agent.not_accessible_bins.append(bin.position)
                            self.agent.no_path.append(bin.position)
                                
        # Send claim message to all trucks
        async def send_claim_message(self, bin, cost):
            claim_msg = Message()
            claim_msg.set_metadata("performative", "claim-bin")
            claim_msg.body = f"{bin.position[0]},{bin.position[1]},{cost},{self.agent.fuel},{self.agent.max_load - self.agent.load}"
            for truck in self.agent.environment.trucks:
                if truck.jid != self.agent.jid:
                    claim_msg.to = str(truck.jid)
                    await self.send(claim_msg)
                    print(f"[{self.agent.name}] Sent claim message for bin at ({bin.position[1]},{bin.position[0]}) to {truck.jid} due to EXPLORATION.")

    class ReceiveClaimBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=1)
            if msg and msg.metadata.get("performative") == "claim-bin" and not self.agent.is_broken and not self.agent.emergency:
                bin_data = msg.body.split(",")
                bin_position = (int(bin_data[0]), int(bin_data[1]))
                other_cost = int(bin_data[2])
                other_fuel = int(bin_data[3])
                other_capacity = int(bin_data[4])
                print(f"[{self.agent.name}] recebeu claim-bin de [{msg.sender}]")
                if self.agent.exploration_bin != None and self.agent.exploration_bin.position == bin_position and self.agent.is_busy:
                    confirm_msg = Message(to=str(msg.sender))
                    confirm_msg.set_metadata("performative", "decline-claim")
                    confirm_msg.body = f"{bin_position[0]},{bin_position[1]}"
                    print(f"[{self.agent.name}] Warning other truck {msg.sender} to realise claim for bin at ({bin_position[1]},{bin_position[0]}). (My bin)")
                    await self.send(confirm_msg)
                elif self.agent.exploration_bin != None and self.agent.exploration_bin.position == bin_position and not self.agent.is_broken and not self.agent.is_busy:
                    self.agent.collab += 1
                    print(f"[{self.agent.name}] avaliando...")
                    my_cost = self.agent.get_cost(self.agent.position, bin_position)
                    my_fuel = self.agent.fuel
                    my_capacity = self.agent.max_load - self.agent.load

                    # Deterministic negotiation logic
                    my_id = self.agent.jid
                    other_id = str(msg.sender)
                    negotiate = self.evaluate_negotiation(
                        my_cost, other_cost, my_fuel, other_fuel,
                        my_capacity, other_capacity,
                        my_id, other_id
                    )

                    if negotiate:  # Outro truck deve ganhar
                        print(f"[{self.agent.name}] Realise claim for bin ({bin_position[1]},{bin_position[0]}) to {msg.sender}. (Someone else's bin)")
                        self.agent.exploration_bin = None
                        self.agent.where = None
                        self.agent.current_path = None
                        self.agent.is_busy = False
                        self.agent.not_accessible_bins.append(bin_position)
                    else:
                        # Este truck mantém o claim e informa o outro truck tem de ceder o bin
                        confirm_msg = Message(to=str(msg.sender))
                        confirm_msg.set_metadata("performative", "decline-claim")
                        confirm_msg.body = f"{bin_position[0]},{bin_position[1]}"
                        print(f"[{self.agent.name}] Warning other truck {msg.sender} to realise claim for bin at ({bin_position[1]},{bin_position[0]}). (My bin)")
                        await self.send(confirm_msg)
                else:
                    self.agent.not_accessible_bins.append(bin_position)
                    print(f"apenas adicionou ({bin_position[1]},{bin_position[0]}) à lista de não acessiveis")

        def evaluate_negotiation(self, my_cost, other_cost, my_fuel, other_fuel, my_capacity, other_capacity, my_id, other_id):
            print(f"[{self.agent.jid}] Negotiation details:")
            print(f"  My cost: {my_cost}, Other cost: {other_cost}")
            print(f"  My fuel: {my_fuel}, Other fuel: {other_fuel}")
            print(f"  My capacity: {my_capacity}, Other capacity: {other_capacity}")
            print(f"  My ID: {my_id}, Other ID: {other_id}")

            # Prioridade 1: Truck com maior capacidade disponível
            if my_capacity > other_capacity:
                print("[Decision] I have higher capacity.")
                return False
            elif my_capacity < other_capacity:
                print("[Decision] Other has higher capacity.")
                return True

            # Prioridade 2: Truck com menor custo
            if my_cost < other_cost:
                print("[Decision] I have lower cost.")
                return False
            elif my_cost > other_cost:
                print("[Decision] Other has lower cost.")
                return True

            # Prioridade 3: Truck com mais combustível
            if my_fuel > other_fuel:
                print("[Decision] I have more fuel.")
                return False
            elif my_fuel < other_fuel:
                print("[Decision] Other has more fuel.")
                return True

            # Prioridade 4: Desempate determinístico pelo ID
            if str(my_id) < str(other_id):
                print("[Decision] I win by ID.")
                return False
            else:
                print("[Decision] Other wins by ID.")
                return True

    class ReceiveAllocatationBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout = 1)
            if msg and msg.metadata.get("performative") == "allocate-task":
                bin_pos = tuple(map(int, msg.body.split(",")))
                if not self.agent.is_busy and not self.agent.emergency and not self.agent.is_broken and not bin_pos in self.agent.no_path:
                    if (self.agent.exploration_bin != None):
                        await self.send_release_message(self.agent.exploration_bin.position)
                    self.agent.current_path = None
                    self.agent.exploration_bin = self.agent.environment.get_bin_at_position(bin_pos)
                    self.agent.where = "bin"
                    self.agent.is_busy = True
                    for truck in self.agent.environment.trucks:
                        if (truck.jid != self.agent.jid):
                            await self.warn_bin(bin_pos)
                            await self.prepare_proposal(truck.jid, bin_pos)
                    await asyncio.sleep(2)  # Espera por respostas
                    if bin_pos not in self.agent.not_accessible_bins:
                        print(f"[{self.agent.name}] Selected bin at ({bin_pos[1]},{bin_pos[0]}) for resolve ALLOCATION problem.")
                        _, self.agent.current_path = self.agent.get_shortest_path(bin_pos)
                        self.agent.collab += 1

        # Send release message to all trucks
        async def send_release_message(self, bin_position):
            release_msg = Message()
            release_msg.set_metadata("performative", "release-bin")
            release_msg.body = f"{bin_position[0]},{bin_position[1]}"
            for truck in self.agent.environment.trucks:
                if truck.jid != self.agent.jid:
                    release_msg.to = str(truck.jid)
                    await self.send(release_msg)
            print(f"[{self.agent.name}] Sent release message for bin at ({bin_position[1]},{bin_position[0]}).")

        async def warn_bin(self, pos):
            warn_msg = Message()
            warn_msg.set_metadata("performative", "resolve-problem")
            bin = self.agent.environment.get_bin_at_position(pos)
            warn_msg.to = str(bin.jid)
            await self.send(warn_msg)
            print("Há um truck interessado no bin com problema")

        async def prepare_proposal(self, truck_name, bin_pos):
            cost, _ = self.agent.get_shortest_path(bin_pos)
            proposal = Message()
            proposal.set_metadata("performative", "claim-bin")
            proposal.body = f"{bin_pos[0]},{bin_pos[1]},{cost},{self.agent.fuel},{self.agent.max_load - self.agent.load}"
            proposal.to = str(truck_name)
            await self.send(proposal)
            print(f"[{self.agent.name}] Truck sent ALLOCATION claim bin at {bin_pos} with cost {cost}.")
                        
    class ReceiveReleaseBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout = 1)
            if msg and msg.metadata.get("performative") == "release-bin":
                released_bin = tuple(map(int, msg.body.split(",")))
                if released_bin in self.agent.not_accessible_bins:
                    self.agent.not_accessible_bins.remove(released_bin)

    class ReceiveDeclineClaimBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=1)
            if msg and msg.metadata.get("performative") == "decline-claim":
                bin_position = tuple(map(int, msg.body.split(",")[:2]))
                print(f"[{self.agent.name}] Received decline-claim for bin at ({bin_position[1]},{bin_position[0]}) from [{msg.sender}].")
                if self.agent.exploration_bin != None and self.agent.exploration_bin.position == bin_position:
                    self.agent.exploration_bin = None
                    self.agent.where = None
                    self.agent.current_path = None
                    self.agent.is_busy = False
                    print(f"[{self.agent.name}] Released bin at ({bin_position[1]},{bin_position[0]}) after decline-claim.")
                self.agent.not_accessible_bins.append(bin_position)

    class CheckStatusBehaviour(CyclicBehaviour):
        async def run(self):
            # Monitor truck's status and handle emergencies
            if not self.agent.emergency and not self.agent.is_broken:
                if not self.agent.has_enough_fuel():
                    print(f"[{self.agent.name}] Low fuel. Returning to central.")
                    self.agent.is_busy = True
                    self.agent.emergency = True
                    if (self.agent.exploration_bin != None):
                        self.send_release_message(self.agent.exploration_bin.position)
                        self.agent.exploration_bin = None
                        self.agent.where = None 
                        self.agent.current_path = None
                    await self.return_to_central()
                elif self.agent.is_full():
                    print(f"[{self.agent.name}] Full load. Returning to central.")
                    self.agent.is_busy = True
                    self.agent.emergency = True
                    if (self.agent.exploration_bin != None):
                        self.send_release_message(self.agent.exploration_bin.position)
                        self.agent.exploration_bin = None
                        self.agent.where = None
                        self.agent.current_path = None
                    await self.return_to_central()

        async def return_to_central(self):
            print(f"[{self.agent.name}] Returning to central at {self.agent.environment.central}.")
            _, self.agent.current_path = self.agent.get_shortest_path(self.agent.environment.central)
            self.agent.where = 'central'
            
        # Send release message to all trucks
        async def send_release_message(self, bin_position):
            release_msg = Message()
            release_msg.set_metadata("performative", "release-bin")
            release_msg.body = f"{bin_position[0]},{bin_position[1]}"
            for truck in self.agent.environment.trucks:
                if truck.jid != self.agent.jid:
                    release_msg.to = str(truck.jid)
                    await self.send(release_msg)
            print(f"[{self.agent.name}] Sent release message for bin at ({bin_position[1]},{bin_position[0]}). Going back to central")

    def has_enough_fuel(self):
        # Checks if there's enough fuel to return to the central
        cost, _ = self.get_shortest_path(self.environment.central)
        return self.fuel > cost

    def is_full(self):
        # Checks if the truck is at 90% capacity or more
        return self.load >= 0.9 * self.max_load

    class MoveToBehaviour(CyclicBehaviour):
        async def run(self):
            if self.agent.changes == True:
                await self.receive_environment_update()
            elif self.agent.is_broken == True:
                await self.broke_down()
            else:
                if self.agent.current_path != None:
                    if self.agent.current_path == None:
                        return
                    path = self.agent.current_path
                    if len(self.agent.current_path) != 1:
                        curr_node_name = path[0]
                        next_node_name = path[1]
                        next_pos = self.agent.environment.get_pos_from_node_name(next_node_name)
                        self.agent.environment.move_truck(self, next_pos)
                        edge_data = self.agent.environment.g.get_edge_data(curr_node_name, next_node_name)
                        w_edge = edge_data["weight"]
                        self.agent.fuel -= w_edge
                        self.agent.total_fuel += w_edge
                        self.agent.total_distance += 1
                        await asyncio.sleep(w_edge)
                        if self.agent.current_path != None and len(self.agent.current_path) != 1 and next_node_name == self.agent.current_path[1]:
                            self.agent.current_path = self.agent.current_path[1:]
                            print("cut path")
                    else:
                        print("Chegou ao destino")
                        if self.agent.where == 'bin':
                            print("vai coletar lixo?")
                            await self.collect_waste()
                            self.agent.current_path = None
                            self.agent.exploration_bin = None
                            self.agent.where = None
                            self.agent.is_busy = False
                        elif self.agent.where == 'central':
                            print("vai dar refill?")
                            await self.refill()
                            self.agent.current_path = None
                            self.agent.exploration_bin = None
                            self.agent.where = None
                            self.agent.is_busy = False
        
        async def receive_environment_update(self):
            # Ver se já há caminho para os bins que não tinham caminho
            self.agent.changes = False
            for bin_pos in self.agent.no_path:
                try:
                    _, p = self.agent.get_shortest_path(bin_pos)
                    self.agent.no_path.remove(bin_pos)
                    self.agent.not_accessible_bins.remove(bin_pos)
                except Exception as e:
                    pass
            
            # Agora vamos ver se o caminho do truck deve ser alterado
            if self.agent.current_path != None:
                path = self.agent.current_path
                self.agent.current_path = None
                final_pos = self.agent.environment.get_pos_from_node_name(path[-1])
                try:
                    _, new_path = self.agent.get_shortest_path(final_pos)
                    self.agent.current_path = new_path
                except Exception as e:
                            print(f"[{self.agent.name}] Mudanças na estrada. Já não exite caminho para o bin em ({final_pos[1]},{final_pos[0]})")
                            self.agent.exploration_bin = None
                            self.agent.where = None
                            self.agent.not_accessible_bins.append(final_pos)
                            self.agent.no_path.append(final_pos)
                            self.agent.current_path = None
                            self.agent.is_busy = False
                            # Agora temos de dizer ao bin que não vou lá
                            await self.warn_bin(final_pos)
        
        async def warn_bin(self, pos):
            warn_msg = Message()
            warn_msg.set_metadata("performative", "problem")
            bin = self.agent.environment.get_bin_at_position(pos)
            warn_msg.to = str(bin.jid)
            await self.send(warn_msg)
            print(f"[{self.agent.name}] Can't go to bin ({bin.position[1]},{bin.position[0]}). Bin warned.")

        async def collect_waste(self):
            bin_at_position = self.agent.environment.get_bin_at_position(self.agent.position)
            if bin_at_position:
                load_to_collect = min(bin_at_position.current_waste, self.agent.max_load - self.agent.load)
                self.agent.load += load_to_collect
                self.agent.collected_waste += load_to_collect
                bin_at_position.current_waste -= load_to_collect
                bin_at_position.is_waiting_for_truck = False
                print(f"[{self.agent.name}] Truck collected {load_to_collect} waste. Current load: {self.agent.load}/{self.agent.max_load}.")
                await self.send_release_message(bin_at_position.position)
            else:
                print(f"[{self.agent.name}] No bin found at the current position.")

        async def refill(self):
            self.agent.fuel = self.agent.max_fuel  # Simula reabastecimento
            self.agent.load = 0  # Simula descarregamento de lixo
            await asyncio.sleep(5)
            self.agent.is_busy = False
            self.agent.emergency = False
            print(f"[{self.agent.name}] Refilled and unloaded at central.")

        async def broke_down(self):
            if (self.agent.is_broken):  
                print(f"[{self.agent.name}] is broken")   
                if self.agent.current_path != None:   
                    bin_pos = self.agent.environment.get_pos_from_node_name(self.agent.current_path[-1])
                    await self.send_release_message(bin_pos)
                    if (self.agent.is_busy and not self.agent.emergency and self.agent.exploration_bin != None):
                        print("Estava busy,  alocar outros trucks")
                        await self.warn_bin(bin_pos)
                        await self.alocate_others_trucks(bin_pos)
                        
                self.agent.exploration_bin = None
                self.agent.current_path = None
                self.agent.where = None
                
                # Tempo que o truck vai ficar sem funcionar
                broken_time = 10
                for i in range (broken_time):
                    await asyncio.sleep(1)
                    print(f"[{self.agent.name}] {broken_time-i} seconds left until normal functionnig")
                print(f"[{self.agent.name}] normal functionnig started")
                
                self.agent.emergency = False
                self.agent.is_broken = False
                self.agent.is_busy = False

        async def alocate_others_trucks(self, bin_position):
            allocate_task_msg = Message()
            allocate_task_msg.set_metadata("performative", "allocate-task")
            allocate_task_msg.body = f"{bin_position[0]},{bin_position[1]}"
            for truck in self.agent.environment.trucks:
                if (truck.jid != self.agent.jid):
                    allocate_task_msg.to = str(truck.jid)
                    await self.send(allocate_task_msg)
                    print(f"[{self.agent.name}] broke down. Asking [{allocate_task_msg.to}] to go to the bin ({bin_position[1]},{bin_position[0]}).")

        # Send release message to all trucks
        async def send_release_message(self, bin_position):
            release_msg = Message()
            release_msg.set_metadata("performative", "release-bin")
            release_msg.body = f"{bin_position[0]},{bin_position[1]}"
            for truck in self.agent.environment.trucks:
                if truck.jid != self.agent.jid:
                    release_msg.to = str(truck.jid)
                    await self.send(release_msg)
            print(f"[{self.agent.name}] Sent release message for bin at {bin_position}.")
            
    class Ajuda(CyclicBehaviour):
        async def run(self):
            if self.agent.current_path == None and self.agent.emergency != False and self.agent.is_broken != False:
                print("--------------- NÃO HÁ ATIVIDADE. DAR RESET A BUSY ---------------------")
                time = self.agent.environment.timer()
                new_time = self.agent.environment.timer()
                while (new_time - time < 5):
                    new_time = self.agent.environment.timer()
                if (self.agent.current_path == None):
                    if self.agent.is_busy == True and self.agent.exploration_bin != None:
                        self.warn_bin(self.agent.exploration_bin.position)
                        self.send_release_message(self.agent.exploration_bin.position)
                        print("--------------- Houve um erro. AJUDA ---------------")
                    self.agent.is_busy = False
        
        async def warn_bin(self, pos):
            warn_msg = Message()
            warn_msg.set_metadata("performative", "problem")
            bin = self.agent.environment.get_bin_at_position(pos)
            warn_msg.to = str(bin.jid)
            await self.send(warn_msg)
            print(f"--------------- [{self.agent.name}] Can't go to bin ({bin.position[1]},{bin.position[0]}). Bin warned. ---------------")
        
        async def send_release_message(self, bin_position):
            release_msg = Message()
            release_msg.set_metadata("performative", "release-bin")
            release_msg.body = f"{bin_position[0]},{bin_position[1]}"
            for truck in self.agent.environment.trucks:
                if truck.jid != self.agent.jid:
                    release_msg.to = str(truck.jid)
                    await self.send(release_msg)
            print(f"--------------- [{self.agent.name}] Sent release message for bin at {bin_position}. ---------------")

    async def setup(self):
        self.add_behaviour(self.ReceiveCFPBehaviour())
        self.add_behaviour(self.ReceiveAcceptanceBehaviour())
        #self.add_behaviour(self.ExploreEnvironmentBehaviour())
        self.add_behaviour(self.ReceiveClaimBehaviour())
        self.add_behaviour(self.ReceiveReleaseBehaviour())
        self.add_behaviour(self.ReceiveDeclineClaimBehaviour())
        self.add_behaviour(self.CheckStatusBehaviour())
        self.add_behaviour(self.MoveToBehaviour())
        self.add_behaviour(self.ReceiveAllocatationBehaviour())
        self.add_behaviour(self.Ajuda())
        print(f"[{self.name}] Truck agent {str(self.jid)} has initialized.")
