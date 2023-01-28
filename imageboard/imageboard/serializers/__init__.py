class Builder(object):
    def __init__(self):
        self.mapped_variables = []

    def serialize(self):
        raise NotImplementedError()


class JSONBuilderError(Exception):
    pass


class JSONBuilder(Builder):
    def __init__(self):
        super(JSONBuilder, self).__init__()
        self.json_node = {}

    def serialize(self) -> dict:
        main_node = {}

        # Sub-nodes
        for json_node_name, attribute_name in self.mapped_variables:
            try:
                attribute_value = getattr(self, attribute_name)
            except AttributeError:
                raise JSONBuilderError("JSON node '%s' in %s class is mapped to non-existing attribute '%s'" % (
                    json_node_name, self.__class__.__name__, attribute_name))

            if isinstance(attribute_value, Builder):
                main_node[json_node_name] = attribute_value.serialize()
                continue
            if attribute_value.__class__ in (dict, str):
                main_node[json_node_name] = attribute_value
            elif type(attribute_value) in (float, int):
                main_node[json_node_name] = attribute_value
            elif attribute_value is None:
                main_node[json_node_name] = None
            elif hasattr(attribute_value, '__iter__'):
                main_node[json_node_name] = []
                for e in attribute_value:
                    if isinstance(e, Builder):
                        main_node[json_node_name].append(e.serialize())
                    else:
                        if hasattr(e, 'serialize'):
                            try:
                                serialized = e.serialize()
                            except Exception as error:
                                raise JSONBuilderError(
                                    f"Error when trying to serialize '{e.__class__}': {e.message}"
                                ) from error
                            else:
                                if not isinstance(serialized, dict):
                                    raise JSONBuilderError(
                                        f"'{e.__class__.__name__}' has serialize() method,"
                                        f" but return type of such method is invalid."
                                        f" dict is expected. Got {serialized.__class__.__name__}"
                                    )
                                main_node[json_node_name].append(serialized)
                        else:
                            main_node[json_node_name].append(e)
            else:
                raise JSONBuilderError("'%s' is not a serialisable element" % attribute_value.__class__)

        return main_node


def serialize_date(date):
    return date.strftime("%Y-%m-%d %H:%M:%S")
