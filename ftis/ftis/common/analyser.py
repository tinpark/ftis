import os
from ftis.common.exceptions import NotYetImplemented
from ftis.common.utils import read_yaml
from ftis.common.types import Ftypes


class FTISAnalyser:
    """Every analyser inherits from this class"""
    def __init__(self, parent_process):
        self.parent_process = parent_process
        self.config = self.parent_process.config
        self.logger = self.parent_process.logger
        self.input = ""
        self.output = ""
        self.input_type = ""
        self.output_type = ""
        self.order:int = -1
        self.parameters = {}
        self.parameter_template = {}
        self.name = ""
        self.cache_exists = False
    
    def log(self, log_text):
        self.logger.debug(f"{self.name}: {log_text}")

    def validate_parameters(self):
        """Validates parameters from the config against the template"""
        self.log(f"Validating parameters for {self.name}")
        module_parameters = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "..",
            "analysers",
            self.name,
            "parameters.yaml"
        )
        self.parameter_template = read_yaml(module_parameters)

        # Put the caching parameter in no matter what
        if not self.parameter_template:
            self.parameter_template = {"cache" : {"default" : False}}
        else:
            self.parameter_template["cache"] = {"default" : False} 

        if self.parameter_template:
            for key in self.parameter_template:
                self.parameters[key] = self.parameter_template[key]["default"]
        try:
            for parameter in self.config["analysers"][self.name]:
                self.parameters[parameter] = self.config["analysers"][self.name][parameter]
        except TypeError:
            self.log("using all default parameters")
            
        self.set_output()

    def set_output(self):
        """Create the output for path/type"""
        out = f"{self.name}{self.output_type}"
        self.output = os.path.join(
            self.parent_process.base_dir, 
            f"{self.order}_{out}")

        
        
        if os.path.exists(self.output):
            metadata = 
            if self.parent_process.base_dir
            self.cache_exists = True # set a flag to say cache exists once we know the output
        
        if self.output_type == Ftypes.folder and not os.path.exists(self.output):
            os.makedirs(self.output)

        self.log("Setting outputs")

    def do(self):
        self.log("Executing process")

        if self.parameters["cache"] == True:
            if self.cache_exists:
                self.log("was cached")
                self.parent_process.fprint(f"{self.name} was cached!")
            else:
                self.run()
                self.log(f"{self.name} wanted to be cached but there was no cache")
        else:
            self.run()
            self.log("was not cached")

        self.log("Finished processing")
        
    def run(self):
        """Method for running the processing chain from input to output"""
        
