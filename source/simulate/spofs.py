from simulate.spof import Spof
class Spofs:
    def __init__(self):
        self.spof_list = []

    def register_spof(self, name, fiber_name_list, cos_protect_list):
        self.spof_list.append(Spof(name, fiber_name_list, cos_protect_list))

