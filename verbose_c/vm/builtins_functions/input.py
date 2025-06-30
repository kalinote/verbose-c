from verbose_c.object.t_string import VBCString
from verbose_c.object.t_null import VBCNull

def native_input(prompt_arg=None):
    """
    内置的 input 函数实现
    """
    if prompt_arg is None or isinstance(prompt_arg, VBCNull):
        prompt = ""
    else:
        prompt = str(prompt_arg)
        
    user_input = input(prompt)
    return VBCString(user_input)
