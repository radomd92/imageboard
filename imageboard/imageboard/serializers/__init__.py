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
            except AttributeError as e:
                raise JSONBuilderError(
                    f"JSON node '{json_node_name}' in {self.__class__.__name__} class is mapped to non-existing attribute '{attribute_name}'"
                ) from e

            if isinstance(attribute_value, Builder):
                main_node[json_node_name] = attribute_value.serialize()
                continue
            if attribute_value.__class__ in (dict, str) or type(
                attribute_value
            ) in (float, int):
                main_node[json_node_name] = attribute_value
            elif attribute_value is None:
                main_node[json_node_name] = None
            elif hasattr(attribute_value, '__iter__'):
                main_node[json_node_name] = []
                for e in attribute_value:
                    if isinstance(e, Builder):
                        main_node[json_node_name].append(e.serialize())
                    elif hasattr(e, 'serialize'):
                        try:
                            serialized = e.serialize()
                        except Exception as error:
                            raise JSONBuilderError(
                                f"Error when trying to serialize '{e.__class__}': {e.message}"
                            ) from error
                        else:
                            if isinstance(serialized, dict):
                                main_node[json_node_name].append(serialized)
                            else:
                                raise JSONBuilderError(
                                    f"'{e.__class__.__name__}' has serialize() method,"
                                    f" but return type of such method is invalid."
                                    f" dict is expected. Got {serialized.__class__.__name__}"
                                )
                    else:
                        main_node[json_node_name].append(e)
            else:
                raise JSONBuilderError(
                    f"'{attribute_value.__class__}' is not a serialisable element"
                )

        return main_node


def serialize_date(date):
    return date.strftime("%Y-%m-%d %H:%M:%S")
