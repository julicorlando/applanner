-- Complete commercial CRUD and explicit entitlement permissions.
INSERT IGNORE INTO permissions(slug,name) VALUES
('customers.edit','Editar clientes'),
('services.edit','Editar serviços');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('customers.edit','services.edit')
WHERE r.slug IN('owner','manager');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug='customers.edit'
WHERE r.slug='reception';
