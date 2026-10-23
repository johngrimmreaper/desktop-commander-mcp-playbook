"""Strict, bounded YAML parser for operator inventories (no secret disclosure)."""
import yaml


class StrictInventoryLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError('Aliases are not supported in MCP inventories')
        return super().compose_node(parent, index)


def strict_mapping(loader, node):
    value = {}
    for key_node, value_node in node.value:
        if key_node.tag == 'tag:yaml.org,2002:merge':
            raise yaml.YAMLError('Merge keys are not supported in MCP inventories')
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in value:
            raise yaml.YAMLError('Inventory keys must be unique strings')
        value[key] = loader.construct_object(value_node, deep=True)
    return value


StrictInventoryLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                                      strict_mapping)


def load_inventory(source):
    if not isinstance(source, str) or len(source) > 262144 or '\t' in source:
        raise yaml.YAMLError('MCP inventory is oversized or has tab indentation')
    return yaml.load(source, Loader=StrictInventoryLoader)
