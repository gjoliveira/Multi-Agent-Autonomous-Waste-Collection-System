import spade
import random
import asyncio
from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour, CyclicBehaviour, OneShotBehaviour
from spade.message import Message
import ast



class BinAgent(spade.agent.Agent):
    def __init__(self, jid, password, position, environment) : 
        super().__init__(jid, password)
        self.position = position
        self.environment = environment
        self.max_capacity = 100
        self.current_waste = random.randint(0, int(self.max_capacity * 0.4))
        self.received_responses = {}
        self.accumulation_period =  random.randint(5,8)
        self.is_waiting_for_truck = False
        self.sent_colection_request = False
        self.resolving = 0
        self.collection_time = []   # Guarda o tempo que demorou a ser recolhido 
        self.waste = None
        self.time = None

    class WasteAccumulationBehaviour(PeriodicBehaviour):
        async def run(self):
            accumulation = random.randint(0,10)
            if self.agent.max_capacity - self.agent.current_waste < accumulation:
                self.agent.curren_waste = 100
                print(f"[{self.agent.name}] [({self.agent.position[1]},{self.agent.position[0]})] está cheio. Aguardando recolha") #Temos de decidir o que acontece com os lixos que já estão cheios... Damos mais prioridade a esses??
                if self.agent.sent_colection_request == False and self.agent.is_waiting_for_truck == False:
                    self.agent.sent_colection_request = True
                    self.agent.received_responses = {}
                    await self.send_cfp_to_trucks()
                return

            self.agent.current_waste += accumulation
            print(f"[{self.agent.name}] Waste level : {self.agent.current_waste} / {self.agent.max_capacity}. Accumulation = {accumulation}")

            if self.agent.current_waste < 70:
                self.agent.is_waiting_for_truck = False
                self.agent.sent_colection_request = False

            if self.agent.current_waste >= 0.7 * self.agent.max_capacity and self.agent.sent_colection_request == False and self.agent.is_waiting_for_truck == False:
                print(f"[{self.agent.name}] [({self.agent.position[1]},{self.agent.position[0]})] Waste level reached >= 70%. Sending collection request")
                self.agent.sent_colection_request = True
                self.agent.received_responses = {}
                await self.send_cfp_to_trucks()
            

    
        async def send_cfp_to_trucks(self):
            # Envia CFP para todos os trucks registrados no environment
            print(f"[{self.agent.name}] Attempting to send CFP")
            for truck in self.agent.environment.trucks:
                if not truck.is_busy:
                    cfp_message = Message(to = str(truck.jid))
                    cfp_message.set_metadata("performative", "cfp")
                    cfp_message.body = f"{self.agent.position[0]},{self.agent.position[1]}"
                    await self.send(cfp_message)
                    print(f"[{self.agent.name}] [({self.agent.position[1]},{self.agent.position[0]})] CFP enviado ao truck {truck.jid}.")
        
            # Adiciona um comportamento de espera para coletar as respostas dos trucks
            wait_for_responses=self.agent.WaitForResponsesBehaviour()
            self.agent.add_behaviour(wait_for_responses)

    class ReceiveProposalBehaviour(CyclicBehaviour):
        async def run(self):
            # Recebe propostas ou recusas dos trucks
            msg = await self.receive(timeout=1)
            if msg:
                if msg.metadata.get("performative") == "propose":
                    # Extrai caminho, custo e capacidade disponível da proposta do truck
                    path_str, estimated_cost, available_capacity, fuel = msg.body.split(";")
                    estimated_cost = int(estimated_cost)
                    available_capacity = int(available_capacity)
                    # Armazena a proposta, incluindo o path
                    self.agent.received_responses[msg.sender] = {
                        'type': 'proposal',
                        'cost': estimated_cost,
                        'available_capacity': available_capacity,
                        'fuel': fuel,
                        'path': path_str
                    }
                    print(f"[{self.agent.name}] Proposta recebida de {msg.sender}: Capacidade {available_capacity}, Custo {estimated_cost}")
                elif msg.metadata.get("performative") == "decline":
                    # Armazena a recusa como resposta
                    self.agent.received_responses[msg.sender] = {'type': 'decline'}
                    print(f"[{self.agent.name}] Rejeição recebida de {msg.sender}")

    class WaitForResponsesBehaviour(OneShotBehaviour):
        async def run(self):
            await asyncio.sleep(3) # wait for trucks responses to be sent
            # Finaliza a espera quando o tempo expira e avalia as propostas
            print(f"[{self.agent.name}] Tempo de espera expirado. Avaliando propostas...")
            await self.evaluate_proposals()
            self.agent.received_respondes = {}
            self.kill()  # Encerra o comportamento após a avaliação

        async def evaluate_proposals(self):
            # Seleciona a melhor proposta entre as respostas válidas (não decline)
            best_proposal = None
            for truck_jid, response in self.agent.received_responses.items():
                if response['type'] == 'proposal':
                    # get the right truck by its jid
                    for t in self.agent.environment.trucks:
                        if(t.jid == truck_jid):
                            cost, path = t.get_shortest_path(self.agent.position)
                            is_busy = t.is_busy                   
                            # atualiza a proposta se entrtanto o truck se mexeu em exploração
                            if(is_busy==False and (cost!=response['cost'] or path!=ast.literal_eval(response['path']))):
                                response['cost']=cost
                                response['path']=f"{path}"
                    
                    if (not is_busy  and
                        (best_proposal is None or                        
                        response['available_capacity'] > best_proposal['available_capacity'] or
                        (response['available_capacity'] == best_proposal['available_capacity'] and response['cost'] < best_proposal['cost']) or
                        (response['available_capacity'] == best_proposal['available_capacity'] and response['cost'] == best_proposal['cost'] and response['fuel'] > best_proposal['fuel']) or
                        (response['available_capacity'] == best_proposal['available_capacity'] and response['cost'] == best_proposal['cost'] and response['fuel'] > best_proposal['fuel']) and response['truck_jid'] < best_proposal['fuel'])):
                        # Atualiza a melhor proposta com base na capacidade e custo
                        best_proposal = {
                            'truck_jid': truck_jid,
                            'cost': response['cost'],
                            'available_capacity': response['available_capacity'],
                            'fuel': response['fuel'],
                            'path': response['path']
                        }

            if best_proposal:
                # Se houver uma proposta válida, envia aceitação
                if self.agent.current_waste >= 70:
                    await self.accept_best_proposal(best_proposal)
                else:
                    self.agent.is_waiting_for_truck = False
                    self.agent.sent_colection_request = False
            else:
                print(f"[{self.agent.name}] Nenhuma proposta válida recebida.")
                self.agent.sent_colection_request = False

        async def accept_best_proposal(self, best_proposal):
            # Envia a aceitação ao truck, incluindo o path no corpo da mensagem
            accept_msg = Message(to = str(best_proposal['truck_jid']))
            accept_msg.set_metadata("performative", "accept")
            path_str = best_proposal['path']
            accept_msg.body = path_str
            await self.send(accept_msg)
            self.agent.is_waiting_for_truck = True
            self.agent.sent_colection_request = False
            print(f"[{self.agent.name}] Aceitação enviada ao truck {best_proposal['truck_jid']} com o caminho: {best_proposal['path']}.")

    class ReceiveProblemBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout = 1)
            if msg and msg.metadata.get("performative") == "problem":
                # Adiciona um comportamento de espera para coletar as respostas dos trucks
                wait_for_problem_responses = self.agent.WaitForProblemResolveBehaviour()
                self.agent.add_behaviour(wait_for_problem_responses)
                print("O bin detetou problema")

    class ReceiveProblemResolveBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=1)
            if msg:
                if msg.metadata.get("performative") == "resolve-problem":
                    self.agent.resolving += 1

    class WaitForProblemResolveBehaviour(OneShotBehaviour):
        async def run(self):
            # Esperar para ver se alguem vem resolver o problema
            await asyncio.sleep(3)
            print("Tempo de espera para resolução acabou")
            if self.agent.resolving == 0:
                self.agent.is_waiting_for_truck = False
                self.agent.sent_colection_request = False
            self.agent.resolving = 0
            self.kill()

    class GetBinsTimeBehaviour(CyclicBehaviour):
        async def run(self):
            if self.agent.waste == None and self.agent.current_waste >= 0.4*self.agent.max_capacity:
                self.agent.waste = self.agent.current_waste
                self.agent.time = self.agent.environment.timer()
            elif self.agent.waste != None:
                if self.agent.waste > self.agent.current_waste:
                    self.agent.collection_time.append(self.agent.environment.timer() - self.agent.time)
                    self.agent.waste = None
                else:
                    self.agent.waste = self.agent.current_waste


    async def setup(self):
        #self.add_behaviour(self.WasteAccumulationBehaviour(period=self.accumulation_period))
        self.add_behaviour(self.ReceiveProposalBehaviour())
        self.add_behaviour(self.ReceiveProblemBehaviour())
        self.add_behaviour(self.ReceiveProblemResolveBehaviour())
        self.add_behaviour(self.GetBinsTimeBehaviour())

        print(f"[{self.name}] Initialized with current waste: {self.current_waste} units.")






# NIVEIS DE ALERTA - Mais prioridade para lixos mais cheios
# PRIORIDADE DE LIXO - zonas mais movimentadas