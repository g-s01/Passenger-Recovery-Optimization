from utils import *
from feasible_flights import *
from cost_function import *
from handle_city_pairs import *
import gurobipy as gp
from gurobipy import GRB
from collections import defaultdict
import time


def get_flight_cabin_mappings(flights, current_mapping=None, flight_index=0):
    """
    To generate the tuple of all possible cabin Mappings.
    Takes FT as input
    Returns the list of cabin_tuples
    """
    if current_mapping is None:
        current_mapping = []

    if flight_index == len(flights):
        yield tuple(cabin for _, cabin in current_mapping)
        return

    flight = flights[flight_index]

    for cabin in flight.cabins:
        current_mapping.append((flight.inventory_id, cabin))
        yield from get_flight_cabin_mappings(flights, current_mapping, flight_index + 1)
        current_mapping.pop()

def optimize_flight_assignments(PNR_List,dp1,city_pairs=False):
    g=create_flight_graph()
    #constants_immutable.all_flights,_,_,_= Get_All_Maps()
    """
        input: List of Impacted PNR objects, optional: city_pairs bool to tell if we have to include city pairs or not
        returns: result dictionary containing Assignments, Non assignments and costs
    """
    model = gp.Model()
    model.Params.LogToConsole = 0 # To avoid printing optimisation info to console
    objective = gp.LinExpr(0)

    # PNR_to_Feasible_Flights now returns a list of tuples of flight objects 
    # Ex. [(Flight1),(Flight1->Flight2),(Flight3)]
    # X_PNR_Constraint -> dictionary where keys are PNR objects and each value is a list of variables for that Particular PNR in its constraint
    # X_Flight_Capacity_Constraint-> dictionary of dictionaries where outer keys are Flight objects and inner keys are cabins, each value is a list of variables for that Particular Flight,Cabin in its constraint

    X_PNR_Constraint = defaultdict(list)
    X_Flight_Capacity_Constraint = defaultdict(lambda: defaultdict(list))

    # Variables
    # X_ijk = 1 if the ith PNR is assigned to the jth flight's kth class
    X = {}

    variable_cnt=0
    PNR_to_FeasibleFlights_map={}
    dp={}
    if not city_pairs:
        for PNR in PNR_List:
            PNR_to_Feasible_Flights(g, constants_immutable.all_flights, PNR, PNR_to_FeasibleFlights_map, dp)

    else:
        for PNR in PNR_List:
            old_arrival_city = constants_immutable.all_flights[PNR.inv_list[-1]].arrival_city
            proposed_arrival_cities = get_city_pairs_cost(old_arrival_city,dp1)
            for city in proposed_arrival_cities:
                PNR_to_Feasible_Flights(g,constants_immutable.all_flights,PNR,PNR_to_FeasibleFlights_map,dp,3,city[0])

    print("Feasible Flights done")
    result = {'Assignments': [],'Non Assignments':[]}
    for PNR in PNR_List:
        for FT in PNR_to_FeasibleFlights_map.get(PNR.pnr_number,[]):
            cabins_tuple = list(get_flight_cabin_mappings(FT))
            for cabin in cabins_tuple:
                # cabin is a tuple Eg: ('FC','PC')
                X[(PNR,FT,cabin)] = model.addVar(vtype=GRB.BINARY, name=f'X_{variable_cnt}')
                variable_cnt+=1
                X_PNR_Constraint[PNR].append(X[(PNR,FT,cabin)])

            for flight_index,flight in enumerate(FT): # Flight is a object
                for cabin in cabins_tuple: # cabin is a tuple Eg:  ('FC','PC') and cabins_tuple = list of cabins
                        X_Flight_Capacity_Constraint[flight][cabin[flight_index]].append(X[(PNR, FT, cabin)] * PNR.PAX)

    print("Variables Created")
    # Constraints
    # Each PNR can be assigned to only one flight class
    for PNR in PNR_List :
        model.addConstr(sum(X_PNR_Constraint[PNR]) <= 1)
        # Penalise non assignment costs (-M(1-sigma(Xi))) - For each PNR
        Non_assignment_Cost = cost_function(PNR,None,None)
        objective+= Non_assignment_Cost - Non_assignment_Cost*sum(X_PNR_Constraint[PNR])

    # The number of assigned passengers should not exceed available seats
    for Flight, constraint_dic in X_Flight_Capacity_Constraint.items():
        for cabin, cabin_list in constraint_dic.items():
            model.addConstr(sum(cabin_list) <= Flight.get_capacity(cabin))

    for PNR in PNR_List:
        for FT in PNR_to_FeasibleFlights_map.get(PNR.pnr_number,[]):
            cabins_tuple = get_flight_cabin_mappings(FT)
            for cabin in cabins_tuple:
                # cabin is a tuple Eg: ('FC', 'PC')
                X_coeff = cost_function(PNR, FT, cabin)
                objective += X_coeff*X[(PNR,FT,cabin)]
                
    print("Constraints added")
    # Set the objective to maximize
    model.setObjective(objective,GRB.MAXIMIZE)
    model.optimize()
    from timings import timings_dict
    timings_dict["Classical_Time"] = model.Runtime*1000
    print("Classical Time (ms):",model.Runtime*1000)
    # Checking if a solution exists
    if model.status == GRB.OPTIMAL:
        # Extract the solution and its cost
        result['Total Cost'] = model.objVal
        timings_dict["Classical_Cost"] = model.ObjVal
        # Populating the result dictionary
        for PNR in PNR_List:
            Assigned = False
            for FT in PNR_to_FeasibleFlights_map.get(PNR.pnr_number,[]):
                cabins_tuple = get_flight_cabin_mappings(FT)
                for cabin in cabins_tuple:
                    # cabin is a tuple Eg: ('FC', 'PC')
                    if X[(PNR, FT, cabin)].x == 1:
                        result['Assignments'].append((PNR, FT, cabin))
                        Assigned = True
            if not Assigned:
                result['Non Assignments'].append(PNR)
        return result
    else:
        return "The problem does not have an optimal solution."

